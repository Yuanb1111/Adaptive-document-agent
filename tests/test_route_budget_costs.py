"""Routing retries and caches preserve usage without making paid requests."""

import re
from unittest.mock import Mock

import pytest
from pydantic import Field, create_model

from adaptive_document_agent.agent.document_discovery import DocumentDiscovery
from adaptive_document_agent.agent.route_budget import RouteBudgetSelection
from adaptive_document_agent.models import AnalysisPageRange, DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.costs import summarize_usage
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.utils.caching import DiskCache


class MeteredMockClient(MockLLMClient):
    """Synthetic TEST currency makes ledger preservation observable, not billing."""

    def generate_text(self, messages, **kwargs):
        response = super().generate_text(messages, **kwargs)
        response.usage = LLMUsage(
            provider="mock", model="mock", input_tokens=100, output_tokens=10,
            cached_input_tokens=0, uncached_input_tokens=100, reasoning_tokens=0,
            estimated_cost=.01, cost_currency="TEST",
            cost_details={"status": "estimated", "estimated_cost_min": .01,
                          "estimated_cost_max": .01, "input_cost_min": .005,
                          "input_cost_max": .005, "output_cost_min": .005, "output_cost_max": .005},
        )
        response.attempts = [{"attempt": 1, "status": "success"}]
        return response


def document(count=240):
    return ParsedDocument(
        document_id="routing-cost", sha256="0" * 64, safe_filename="sample.pdf", page_count=count,
        pages=[DocumentPage(page_number=page, text=f"Evidence on page {page}: raw (1,250) litres.")
               for page in range(1, count + 1)],
    )


def route_response(ranges=((1, 100), (101, 240))):
    return {"selected_page_ranges": [
        {"title": f"Source section {index}", "start_page": start, "end_page": end,
         "reason": "Model-selected primary evidence."}
        for index, (start, end) in enumerate(ranges)
    ]}


def gateway_for(responses, *, cache=None):
    client = MeteredMockClient(responses)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"), cache=cache)
    return client, gateway


def assert_metered_calls(gateway, count):
    assert len(gateway.usage) == count
    assert all(record["stage"] == "discovery" for record in gateway.usage)
    summary = next(row for row in summarize_usage(gateway.usage)["by_currency"] if row["currency"] == "TEST")
    assert summary["priced_calls"] == count
    assert summary["input_tokens"] == count * 100
    assert summary["output_tokens"] == count * 10
    assert summary["estimated_total_min"] == pytest.approx(count * .01)


@pytest.mark.parametrize("bad_selection", [
    {"primary_range_indexes": [0, 0]},
    "not valid JSON",
    {"primary_range_indexes": ["0"]},
])
def test_budget_retry_is_bounded_and_does_not_nest_a_format_repair(bad_selection):
    client, gateway = gateway_for([route_response(), bad_selection, {"primary_range_indexes": [1]}])
    spy = Mock(wraps=gateway.generate_structured)
    gateway.generate_structured = spy
    selected = DocumentDiscovery(gateway).route(document())
    assert [(item.start_page, item.end_page) for item in selected] == [(101, 240)]
    assert len(client.calls) == 3
    assert [record["operation"] for record in gateway.usage] == [
        "DocumentRoute", "RouteBudgetSelection", "RouteBudgetSelection",
    ]
    assert all(call.kwargs["allow_repair"] is False for call in spy.call_args_list[1:])
    assert all("Repair FORMAT ONLY" not in message["content"]
               for messages in client.calls for message in messages)
    assert_metered_calls(gateway, 3)


def test_failed_budget_retry_stops_and_keeps_every_metered_response():
    invalid = {"primary_range_indexes": [99]}
    client, gateway = gateway_for([route_response(), invalid, invalid])
    with pytest.raises(ValueError, match="after one refinement attempt"):
        DocumentDiscovery(gateway).route(document())
    assert len(client.calls) == 3
    assert_metered_calls(gateway, 3)


def test_oversized_range_refinement_keeps_late_model_selected_evidence():
    client, gateway = gateway_for([
        route_response(((1, 240),)), {"primary_range_indexes": [0]},
        {"primary_range_indexes": [0], "refined_ranges": [
            {"range_index": 0, "start_page": 161, "end_page": 240,
             "reason": "Complete late source section contains primary measurements."},
        ]},
    ])
    source = document()
    original = source.model_dump()
    selected = DocumentDiscovery(gateway).route(source)
    assert [(item.start_page, item.end_page) for item in selected] == [(161, 240)]
    assert "primary measurements" in selected[0].reason
    assert len(client.calls) == 3 and source.model_dump() == original
    assert_metered_calls(gateway, 3)


def test_ranked_complete_ranges_fit_without_an_unnecessary_retry():
    client, gateway = gateway_for([route_response(), {"primary_range_indexes": [1, 0]}])
    selected = DocumentDiscovery(gateway).route(document())
    assert [(item.start_page, item.end_page) for item in selected] == [(101, 240)]
    assert "lower-priority" in selected[0].reason
    assert len(client.calls) == 2
    assert_metered_calls(gateway, 2)


def test_repeated_valid_route_is_free_app_cache_with_original_usage_retained(tmp_path):
    client, gateway = gateway_for(
        [route_response(), {"primary_range_indexes": [1]}], cache=DiskCache(tmp_path),
    )
    discovery = DocumentDiscovery(gateway)
    selected = discovery.route(document())
    assert_metered_calls(gateway, 2)
    assert discovery.route(document()) == selected
    assert len(client.calls) == 2
    assert [record["operation"] for record in gateway.usage[2:]] == ["DocumentRoute", "RouteBudgetSelection"]
    assert all(record["cache_hit"] and record["estimated_cost"] == 0 for record in gateway.usage[2:])
    assert all(record["input_tokens"] == record["output_tokens"] == 0 for record in gateway.usage[2:])
    totals = summarize_usage(gateway.usage)["by_currency"]
    assert sum(row["app_cache_hits"] for row in totals) == 2
    assert sum(row["known_cost_min"] for row in totals) == pytest.approx(.02)


def test_new_budget_schema_does_not_reuse_old_semantically_invalid_cache(tmp_path):
    legacy_schema = create_model(
        "RouteBudgetSelection",
        primary_range_indexes=(list[int], Field(default_factory=list, min_length=1, max_length=4)),
    )
    cache = DiskCache(tmp_path)
    messages = [{"role": "user", "content": "Choose primary evidence ranges within the page budget."}]
    old_client, old_gateway = gateway_for([{"primary_range_indexes": [0, 1]}], cache=cache)
    old_gateway.generate_structured(messages, legacy_schema, stage="discovery")
    client, gateway = gateway_for([{"primary_range_indexes": [1]}], cache=cache)
    result = gateway.generate_structured(messages, RouteBudgetSelection, stage="discovery", allow_repair=False)
    assert result.primary_range_indexes == [1]
    assert len(old_client.calls) == len(client.calls) == 1
    assert not gateway.usage[0].get("cache_hit")
    assert gateway.generate_structured(messages, RouteBudgetSelection, stage="discovery", allow_repair=False) == result
    assert len(client.calls) == 1 and gateway.usage[-1]["estimated_cost"] == 0


def test_overlap_under_unique_page_budget_does_not_buy_a_budget_call():
    client, gateway = gateway_for([route_response(((1, 120), (81, 160)))])
    selected = DocumentDiscovery(gateway).route(document())
    assert [(item.start_page, item.end_page) for item in selected] == [(1, 120), (81, 160)]
    assert len(client.calls) == 1 and gateway.usage[0]["operation"] == "DocumentRoute"
    assert_metered_calls(gateway, 1)


def test_discovery_reads_overlapping_pages_once_without_inventing_gap_coverage():
    client, gateway = gateway_for([
        {"summary": "First evidence section.", "metrics": ["Water volume"]},
        {"summary": "Later evidence section.", "metrics": ["Water volume"]},
        {"document_summary": "Selected evidence sections.", "document_summary_pages": [1, 3, 5, 7, 8]},
    ])
    source = document(10)
    original = source.model_dump()
    ranges = [AnalysisPageRange(title=f"Evidence {index}", start_page=start, end_page=end,
                                reason="Confirmed source scope.")
              for index, (start, end) in enumerate(((1, 3), (3, 4), (7, 8)))]
    profile = DocumentDiscovery(gateway, target_tokens=500).discover(source, routed_ranges=ranges)
    chunk_pages = [int(page) for messages in client.calls[:2]
                   for page in re.findall(r"\[PAGE (\d+)\]", messages[-1]["content"])]
    assert chunk_pages == [1, 2, 3, 4, 7, 8]
    assert len(client.calls) == 3
    assert [record["operation"] for record in gateway.usage] == ["ChunkDiscovery", "ChunkDiscovery", "DiscoveryOverview"]
    assert profile.analysis_page_ranges == [(1, 3), (3, 4), (7, 8)]
    assert profile.document_summary_pages == [1, 3, 7, 8]
    assert profile.metrics == ["Water volume"] and source.model_dump() == original
    assert_metered_calls(gateway, 3)
