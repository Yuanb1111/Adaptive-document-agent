"""The 27th-call overview failure must not discard or repurchase chunk discovery."""

from collections import deque
import json
import re

import pytest

from adaptive_document_agent.agent.document_discovery import DocumentDiscovery
from adaptive_document_agent.models import DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.costs import summarize_usage
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.utils.caching import DiskCache


def _chunk_payload(page):
    # Enough distinct catalog entries to catch accidental resampling or caps.
    return {
        "summary": f"Source summary for page {page}.",
        "important_sections": [f"Section {page} (p. {page})"],
        "time_periods": [f"Period {page}"],
        "units": [f"Reported unit {page}"],
        "currencies": [f"Source currency {page}"],
        "dimensions": [f"Source dimension {page}"],
        "metrics": [f"Metric {page}/{index}" for index in range(20)],
        "entities": [f"Source entity {page}"],
        "important_tables": [f"Table {page} (p. {page})"],
        "important_figures": [f"Figure {page} (p. {page})"],
        "data_quality_notes": [f"Retain conflicting source measure on p. {page}."],
    }


class OverviewFailureClient(MockLLMClient):
    """Strict local response adapter; no SDK, network, or paid model calls."""

    def __init__(self, overview_outcomes):
        super().__init__()
        self.overview_outcomes = deque(overview_outcomes)
        self.operations = []

    def generate_text(self, *args, **kwargs):
        raise AssertionError("Overview recovery must not add a gateway format-repair request")

    def generate_structured(self, messages, response_model, **kwargs):
        self.calls.append(messages)
        operation = response_model.__name__
        self.operations.append(operation)
        finish_reason, output_tokens = "stop", 10
        if operation == "DocumentRoute":
            payload = {"selected_page_ranges": [
                {"title": "Primary evidence", "start_page": 1, "end_page": 24,
                 "reason": "Complete evidence section."},
                {"title": "Background evidence", "start_page": 25, "end_page": 200,
                 "reason": "Additional source context."},
            ]}
        elif operation == "RouteBudgetSelection":
            payload = {"primary_range_indexes": [0]}
        elif operation == "ChunkDiscovery":
            pages = re.findall(r"\[PAGE (\d+)\]", messages[-1]["content"])
            assert len(pages) == 1
            payload = _chunk_payload(int(pages[0]))
        elif operation == "DiscoveryOverview":
            outcome = self.overview_outcomes.popleft()
            if outcome == "length":
                finish_reason, output_tokens = "length", 8192
                # Missing facts cannot be recovered by completing this prefix.
                payload = '{"document_summary":"Incomplete untrusted output'
            elif outcome == "invalid":
                payload = '{"document_summary":['
            else:
                assert outcome == "success"
                payload = {
                    "document_type": "Evidence review",
                    "document_purpose": "Describe the supplied measurements.",
                    "overview_title": "Reported measurements",
                    "document_summary": "The selected sections report measurements and source limitations.",
                    "document_summary_pages": [1, 24],
                    "overview_points": ["Compare compatible evidence only."],
                    "data_quality_notes": ["Cross-section definitions require care."],
                }
        else:
            raise AssertionError(f"Unexpected model operation: {operation}")

        response = LLMResponse(
            text=json.dumps(payload) if isinstance(payload, dict) else payload,
            usage=LLMUsage(
                provider="mock", model="overview-recovery-test", input_tokens=100,
                output_tokens=output_tokens, finish_reason=finish_reason,
                estimated_cost=.01, cost_currency="TEST",
                cost_details={"status": "estimated", "estimated_cost_min": .01,
                              "estimated_cost_max": .01},
            ),
            attempts=[{"attempt": 1, "status": "success"}],
        )
        if not isinstance(payload, dict):
            raise LLMStructuredOutputError("Synthetic overview failure", response=response)
        return response_model.model_validate(payload), response


def _source_document():
    return ParsedDocument(
        document_id="overview-recovery", sha256="d" * 64, safe_filename="source.pdf", page_count=200,
        pages=[DocumentPage(page_number=page, text=f"Source page {page}. " + "evidence " * 500)
               for page in range(1, 201)],
    )


def _setup(tmp_path, outcomes):
    cache = DiskCache(tmp_path)
    client = OverviewFailureClient(outcomes)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="overview-recovery-test"), cache=cache)
    return client, gateway, DocumentDiscovery(gateway, target_tokens=1000, cache=cache)


def _assert_complete_profile(profile):
    for target, source in (
        ("metrics", "metrics"), ("detected_units", "units"),
        ("detected_time_periods", "time_periods"), ("detected_currencies", "currencies"),
        ("entities", "entities"), ("dimensions", "dimensions"),
        ("important_sections", "important_sections"), ("important_tables", "important_tables"),
        ("important_figures", "important_figures"), ("data_quality_notes", "data_quality_notes"),
    ):
        expected = [item for page in range(1, 25) for item in _chunk_payload(page)[source]]
        actual = getattr(profile, target)
        assert all(item in actual for item in expected), target
        assert len(actual) == len(set(actual)), target
    assert len(profile.metrics) == 480
    assert profile.analysis_page_ranges == [(1, 24)]
    assert profile.document_summary_pages == [1, 24]
    assert "Cross-section definitions require care." in profile.data_quality_notes


def test_27th_call_truncation_regenerates_only_overview_and_keeps_all_evidence(tmp_path):
    client, gateway, discovery = _setup(tmp_path, ["length", "success"])
    document = _source_document()
    source_before = document.model_dump()
    profile = discovery.discover(document)

    assert client.operations == ["DocumentRoute", "RouteBudgetSelection"] + ["ChunkDiscovery"] * 24 + ["DiscoveryOverview"] * 2
    assert gateway.usage[26]["status"] == "truncated"
    assert gateway.usage[26]["finish_reason"] == "length"
    assert gateway.usage[26]["output_tokens"] == 8192
    assert gateway.usage[27]["status"] == "success"
    assert document.model_dump() == source_before
    _assert_complete_profile(profile)

    for messages in client.calls[-2:]:
        text = "\n".join(message["content"] for message in messages)
        assert "Source summary for page 1." in text and "Source summary for page 24." in text
        assert "Metric 24/19" not in text
        assert "Incomplete untrusted output" not in text
        assert "Repair FORMAT ONLY" not in text
    totals = summarize_usage(gateway.usage)["by_currency"]
    test_cost = next(item for item in totals if item["currency"] == "TEST")
    assert test_cost["priced_calls"] == 28
    assert test_cost["known_cost_min"] == pytest.approx(.28)


@pytest.mark.parametrize("second_failure", ["length", "invalid"])
def test_second_overview_failure_stops_and_next_run_reuses_all_completed_chunks(tmp_path, second_failure):
    client, gateway, discovery = _setup(tmp_path, ["length", second_failure, "success"])
    document = _source_document()
    with pytest.raises(LLMStructuredOutputError):
        discovery.discover(document)
    assert len(client.calls) == 28
    assert client.operations[-2:] == ["DiscoveryOverview", "DiscoveryOverview"]
    assert all(record["status"] == "success" for record in gateway.usage[:26])
    assert gateway.usage[26]["status"] == "truncated"
    assert gateway.usage[27]["status"] == ("truncated" if second_failure == "length" else "invalid_format")

    boundary = len(gateway.usage)
    profile = discovery.discover(document)
    assert len(client.calls) == 29
    assert client.operations.count("ChunkDiscovery") == 24
    _assert_complete_profile(profile)
    resumed = gateway.usage[boundary:]
    assert [record["operation"] for record in resumed[:-1]] == ["DocumentRoute", "RouteBudgetSelection"] + ["ChunkDiscovery"] * 24
    assert all(record["cache_hit"] and record["estimated_cost"] == 0 for record in resumed[:-1])
    assert all(record["input_tokens"] == record["output_tokens"] == 0 for record in resumed[:-1])
    assert resumed[-1]["operation"] == "DiscoveryOverview" and resumed[-1]["status"] == "success"

    # The successful synthesis also becomes reusable, with no new provider call.
    assert discovery.discover(document) == profile
    assert len(client.calls) == 29
