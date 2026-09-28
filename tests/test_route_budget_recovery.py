"""Routing recovery keeps model priorities and evidence within a real page budget."""

from collections import Counter
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.document_discovery import (
    ChunkDiscovery, DocumentDiscovery, RouteBudgetSelection,
)
from adaptive_document_agent.models import AnalysisPageRange, DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import (
    LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName,
)


def _document(count=240):
    return ParsedDocument(
        document_id="routing-evidence", sha256="9" * 64,
        safe_filename="unknown-document.pdf", page_count=count,
        pages=[DocumentPage(page_number=page, text=f"Evidence page {page}; raw value ({page}).")
               for page in range(1, count + 1)],
    )


def _range(start, end, title="Primary evidence"):
    return {"title": title, "start_page": start, "end_page": end,
            "reason": "Reported measurements and source qualifications"}


def _refinement(start, end, *, index=0):
    return {"range_index": index, "start_page": start, "end_page": end,
            "reason": "Complete evidence subsection selected from the supplied page map"}


def _discovery(responses):
    client = MockLLMClient(responses)
    settings = LLMSettings(provider=ProviderName.MOCK, model="mock",
                           privacy_mode=PrivacyMode.LOCAL_ONLY)
    gateway = LLMGateway(client, settings)
    return DocumentDiscovery(gateway), client, gateway


def _spans(ranges):
    return [(item.start_page, item.end_page) for item in ranges]


def _unique_pages(ranges):
    return {page for item in ranges for page in range(item.start_page, item.end_page + 1)}


def test_giant_range_can_be_refined_to_complete_late_evidence_without_truncation():
    document = _document()
    before = document.model_dump()
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 240)]},
        {"primary_range_indexes": [0], "refined_ranges": [_refinement(180, 240)]},
    ])
    selected = discovery._route_large_document(document, "Prioritise primary evidence")
    assert _spans(selected) == [(180, 240)]
    assert len(_unique_pages(selected)) == 61
    assert len(client.calls) == 2
    assert document.model_dump() == before


def test_unrefined_giant_range_gets_one_semantic_recovery_call():
    discovery, client, gateway = _discovery([
        {"selected_page_ranges": [_range(1, 240)]},
        {"primary_range_indexes": [0]},
        {"primary_range_indexes": [0], "refined_ranges": [_refinement(170, 240)]},
    ])
    selected = discovery._route_large_document(_document(), None)
    assert _spans(selected) == [(170, 240)]
    assert len(client.calls) == 3
    assert all(record["stage"] == "discovery" for record in gateway.usage)
    assert not any(record["status"] == "format_repair" for record in gateway.usage)
    assert gateway.settings.privacy_mode == PrivacyMode.LOCAL_ONLY


def test_multiple_refined_subsections_keep_model_priority_and_replace_the_parent():
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 240)]},
        {"primary_range_indexes": [0],
         "refined_ranges": [_refinement(180, 240), _refinement(1, 120)]},
    ])
    selected = discovery._route_large_document(_document(), None)
    assert _spans(selected) == [(180, 240)]
    assert "1-240" in selected[0].reason
    assert len(client.calls) == 2


def test_overlapping_oversized_candidates_share_one_boundary_map():
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 200), _range(41, 240)]},
        {"primary_range_indexes": [1], "refined_ranges": [_refinement(180, 240, index=1)]},
    ])
    assert _spans(discovery._route_large_document(_document(), None)) == [(180, 240)]
    content = next(message["content"] for message in client.calls[1]
                   if message["content"].startswith("<UNTRUSTED_DOCUMENT_CONTENT>"))
    payload = json.loads(content.split("\n", 1)[1].rsplit("\n", 1)[0])
    boundary_map = payload["oversized_range_page_map"]
    assert Counter(entry["page"] for entry in boundary_map) == Counter(range(1, 241))
    assert all("page_map" not in candidate for candidate in payload["ranges"])


@pytest.mark.parametrize("priority,expected", [([0, 1], [(1, 100)]), ([1, 0], [(101, 240)])])
def test_python_fits_whole_ranges_in_model_priority_order_without_an_extra_call(priority, expected):
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 100, "Earlier evidence"), _range(101, 240, "Later evidence")]},
        {"primary_range_indexes": priority},
    ])
    assert _spans(discovery._route_large_document(_document(), None)) == expected
    assert len(client.calls) == 2


def test_overlapping_ranges_that_fit_unique_budget_need_no_budget_request():
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 120, "Section A"), _range(81, 160, "Section B")]},
    ])
    selected = discovery._route_large_document(_document(), None)
    assert _unique_pages(selected) == set(range(1, 161))
    assert len(client.calls) == 1


def test_ranked_overlapping_choices_are_packed_by_incremental_unique_pages():
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 110), _range(61, 160), _range(161, 240)]},
        {"primary_range_indexes": [0, 1, 2]},
    ])
    selected = discovery._route_large_document(_document(), None)
    assert _unique_pages(selected) == set(range(1, 161))
    assert len(client.calls) == 2


@pytest.mark.parametrize("invalid", [
    {"primary_range_indexes": [99]},
    {"primary_range_indexes": [0, 0]},
    {"primary_range_indexes": [True]},
    {"primary_range_indexes": []},
    {},
    "not valid JSON",
])
def test_invalid_budget_response_has_one_bounded_semantic_retry(invalid):
    discovery, client, gateway = _discovery([
        {"selected_page_ranges": [_range(1, 240)]}, invalid,
        {"primary_range_indexes": [0], "refined_ranges": [_refinement(180, 240)]},
    ])
    assert _spans(discovery._route_large_document(_document(), None)) == [(180, 240)]
    assert len(client.calls) == 3
    assert not any(record["status"] == "format_repair" for record in gateway.usage)


@pytest.mark.parametrize("invalid", [
    {"primary_range_indexes": [0]},
    {"primary_range_indexes": [55]},
    {"primary_range_indexes": [0], "refined_ranges": [_refinement(180, 241)]},
    {"primary_range_indexes": [0], "refined_ranges": [_refinement(220, 180)]},
    {"primary_range_indexes": [0], "refined_ranges": [_refinement(180, 240, index=1)]},
    {},
])
def test_recovery_exhaustion_fails_closed_without_truncation_or_full_document_fallback(invalid):
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 240)]}, invalid, invalid,
    ])
    with pytest.raises(ValueError, match="(?i)(scope|range|budget|160)"):
        discovery.route(_document())
    assert len(client.calls) == 3


def test_refinement_must_stay_inside_its_selected_parent_even_with_valid_document_pages():
    invalid = {"primary_range_indexes": [1], "refined_ranges": [_refinement(150, 180, index=1)]}
    discovery, client, _ = _discovery([
        {"selected_page_ranges": [_range(1, 170), _range(171, 240)]}, invalid, invalid,
    ])
    with pytest.raises(ValueError, match="(?i)(scope|range|budget|160)"):
        discovery._route_large_document(_document(), None)
    assert len(client.calls) == 3


@pytest.mark.parametrize("payload", [
    {}, {"primary_range_indexes": []}, {"primary_range_indexes": [True]},
    {"primary_range_indexes": ["0"]}, {"primary_range_indexes": [1.0]},
    {"primary_range_indexes": [-1]}, {"primary_range_indexes": list(range(13))},
])
def test_budget_selection_requires_explicit_nonempty_strict_indexes(payload):
    with pytest.raises(ValidationError):
        RouteBudgetSelection.model_validate(payload)


def test_budget_schema_accepts_more_than_four_model_ranked_candidates():
    selection = RouteBudgetSelection.model_validate({"primary_range_indexes": list(range(12))})
    assert selection.primary_range_indexes == list(range(12))


@pytest.mark.parametrize("field,value", [
    ("range_index", True), ("range_index", "0"), ("start_page", True),
    ("start_page", "180"), ("end_page", 240.0),
])
def test_refinement_numeric_fields_are_strict(field, value):
    refined = _refinement(180, 240)
    refined[field] = value
    with pytest.raises(ValidationError):
        RouteBudgetSelection.model_validate({"primary_range_indexes": [0], "refined_ranges": [refined]})


def test_overlapping_confirmed_sections_are_understood_once_with_original_scope_preserved(monkeypatch):
    document = _document(10)
    before = document.model_dump()
    ranges = [AnalysisPageRange(**_range(1, 7)), AnalysisPageRange(**_range(5, 10))]
    discovery, client, _ = _discovery([{"document_summary": "Retained evidence", "document_summary_pages": [1, 10, 11]}])
    discovery.target_tokens = 1
    understood = []

    def understand(chunk):
        understood.extend(range(chunk.start_page, chunk.end_page + 1))
        return ChunkDiscovery(summary="Evidence", metrics=[f"Metric {chunk.start_page}"])

    monkeypatch.setattr(discovery, "_discover_chunk", understand)
    profile = discovery.discover(document, routed_ranges=ranges)
    assert Counter(understood) == Counter(range(1, 11))
    assert profile.analysis_page_ranges == [(1, 7), (5, 10)]
    assert profile.document_summary_pages == [1, 10]
    assert len(profile.metrics) == 10 and len(client.calls) == 1
    assert document.model_dump() == before


def test_deduplicating_noncontiguous_scope_does_not_mark_gap_pages_as_reviewed(monkeypatch):
    discovery, _, _ = _discovery([{"document_summary_pages": [1, 2, 3, 4, 5, 6]}])
    ranges = [AnalysisPageRange(**_range(1, 2)), AnalysisPageRange(**_range(5, 6))]
    monkeypatch.setattr(discovery, "_discover_chunk", lambda chunk: ChunkDiscovery(summary="Selected evidence"))
    profile = discovery.discover(_document(6), routed_ranges=ranges)
    assert profile.document_summary_pages == [1, 2, 5, 6]
    assert profile.analysis_page_ranges == [(1, 2), (5, 6)]
