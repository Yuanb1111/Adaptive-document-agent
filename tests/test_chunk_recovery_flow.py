"""Metered local simulations of concurrent discovery and bounded chunk recovery."""

from collections import Counter, deque
import json
import re
from threading import Barrier, Event, Lock

import pytest

from adaptive_document_agent.agent.document_discovery import DocumentDiscovery
from adaptive_document_agent.models import DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.config import PrivacyMode
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.costs import summarize_usage
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.utils.caching import DiskCache


FAILED_PAGES = (93, 94, 95, 96)


def _document():
    pages = []
    for page in range(1, 201):
        source = f"SOURCE_PAGE_{page:04d} Exact value ({page},250), distinct evidence.\n"
        if page == 94:
            source += "Quoted source text, not a page boundary:\n[PAGE 999]\nKeep this literal text.\n"
        source += "Untrusted measurement evidence. " * 40
        # Four actual source pages per normal chunk, including the quoted marker.
        pages.append(DocumentPage(page_number=page, text=source[:1024].ljust(1024)))
    return ParsedDocument(document_id="concurrent-recovery", sha256="e" * 64,
                          safe_filename="source.pdf", page_count=200, pages=pages)


def _discovery_payload(pages):
    return {
        "summary": "Source measurements on pages " + ", ".join(map(str, pages)),
        "important_sections": [f"Section {p} (p. {p})" for p in pages],
        "metrics": [f"Exact source metric {p}" for p in pages],
        "units": [f"Source unit {p}" for p in pages],
        "time_periods": [f"Source period {p}" for p in pages],
        "currencies": [f"Source currency {p}" for p in pages],
        "entities": [f"Entity {p}" for p in pages],
        "dimensions": [f"Dimension {p}" for p in pages],
        "important_tables": [f"Table evidence on p. {p}" for p in pages],
        "important_figures": [f"Figure evidence on p. {p}" for p in pages],
        "data_quality_notes": [f"Keep source conflict on p. {p}." for p in pages],
    }


class ConcurrentRecoveryClient(MockLLMClient):
    """Every provider operation is simulated; no provider factory or SDK is used."""

    supports_concurrent_requests = True

    def __init__(self, outcomes, *, concurrent):
        super().__init__()
        self.outcomes = {tuple(pages): deque(values) for pages, values in outcomes.items()}
        self.lock = Lock()
        self.records = []
        self.active = self.max_active = 0
        self.first_wave = Barrier(4) if concurrent else None
        self.neighbors_recorded = Event()

    def generate_text(self, *args, **kwargs):
        raise AssertionError("Recovery must not purchase a format-repair call")

    def generate_structured(self, messages, response_model, **kwargs):
        operation = response_model.__name__
        pages = tuple(int(value) for value in re.findall(r"SOURCE_PAGE_(\d{4})", messages[-1]["content"])) if operation == "ChunkDiscovery" else ()
        assert "request_metadata" not in kwargs  # Locators stay out of provider options.
        with self.lock:
            self.calls.append(messages)
            self.records.append({"operation": operation, "pages": pages, "messages": messages, "kwargs": kwargs})
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            queue = self.outcomes.get(pages)
            outcome = queue.popleft() if queue else "success"
        try:
            if operation == "DocumentRoute":
                payload = {"selected_page_ranges": [
                    {"title": "Primary evidence", "start_page": 1, "end_page": 96, "reason": "Complete source section."},
                    {"title": "Background", "start_page": 97, "end_page": 200, "reason": "Source context."},
                ]}
            elif operation == "RouteBudgetSelection":
                payload = {"primary_range_indexes": [0]}
            elif operation == "ChunkDiscovery":
                if self.first_wave and pages in ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16)):
                    self.first_wave.wait(timeout=10)
                if pages == FAILED_PAGES:
                    assert self.neighbors_recorded.wait(10), "Other completed chunks were not retained"
                assert pages and all(1 <= page <= 96 for page in pages)
                payload = _discovery_payload(pages)
            elif operation == "DiscoveryOverview":
                payload = {"document_summary": "Source measurements and limitations are retained.",
                           "document_summary_pages": [1, 96]}
            else:
                raise AssertionError(f"Unexpected operation: {operation}")
            response = LLMResponse(
                text=json.dumps(payload) if outcome == "success" else '{"summary":"PARTIAL_FACT_MUST_NOT_SURVIVE',
                usage=LLMUsage(provider="mock", model="fixed-test-model", input_tokens=100,
                               output_tokens=8192 if outcome == "length" else 10,
                               finish_reason="length" if outcome == "length" else "stop",
                               estimated_cost=.01, cost_currency="TEST",
                               cost_details={"status": "estimated", "estimated_cost_min": .01, "estimated_cost_max": .01}),
                attempts=[{"attempt": 1, "status": "success"}],
            )
            if outcome != "success":
                raise LLMStructuredOutputError("Synthetic chunk failure", response=response)
            return response_model.model_validate(payload), response
        finally:
            with self.lock:
                self.active -= 1


class RecordedNeighborsGateway(LLMGateway):
    def _record(self, response, **kwargs):
        super()._record(response, **kwargs)
        completed = sum(row["operation"] == "ChunkDiscovery" and row["status"] == "success" for row in self.usage)
        if completed >= 23:
            self.client.neighbors_recorded.set()


def _setup(tmp_path, outcomes, *, local=False):
    client = ConcurrentRecoveryClient(outcomes, concurrent=not local)
    settings = LLMSettings(
        provider=ProviderName.MOCK if local else ProviderName.DEEPSEEK,
        model="fixed-test-model", discovery_workers=4,
        privacy_mode=PrivacyMode.LOCAL_ONLY if local else PrivacyMode.AUTO,
    )
    cache = DiskCache(tmp_path)
    gateway = RecordedNeighborsGateway(client, settings, cache=cache)
    return client, gateway, DocumentDiscovery(gateway, target_tokens=1024, cache=cache)


def _assert_complete(profile):
    for target, source in (
        ("metrics", "metrics"), ("detected_units", "units"),
        ("detected_time_periods", "time_periods"), ("detected_currencies", "currencies"),
        ("entities", "entities"), ("dimensions", "dimensions"),
        ("important_sections", "important_sections"), ("important_tables", "important_tables"),
        ("important_figures", "important_figures"), ("data_quality_notes", "data_quality_notes"),
    ):
        expected = _discovery_payload(range(1, 97))[source]
        assert set(expected) <= set(getattr(profile, target)), target
    assert len(profile.metrics) == 96
    assert profile.analysis_page_ranges == [(1, 96)]
    assert profile.document_summary_pages == [1, 96]
    assert "PARTIAL_FACT_MUST_NOT_SURVIVE" not in profile.model_dump_json()
    assert "999" not in profile.model_dump_json()


def _assert_cost(gateway, requests, truncated):
    rows = [row for row in gateway.usage if not row.get("cache_hit")]
    assert len(rows) == requests
    assert sum(row["status"] == "truncated" for row in rows) == truncated
    totals = next(row for row in summarize_usage(gateway.usage)["by_currency"] if row["currency"] == "TEST")
    assert totals["priced_calls"] == requests
    assert totals["known_cost_min"] == pytest.approx(requests * .01)
    assert totals["output_tokens"] == truncated * 8192 + (requests - truncated) * 10


@pytest.mark.parametrize("local", [False, True], ids=["four-workers", "local-only"])
def test_one_truncated_chunk_recovers_without_rebuying_23_neighbors(tmp_path, local):
    client, gateway, discovery = _setup(tmp_path, {FAILED_PAGES: ["length"]}, local=local)
    document = _document()
    original = document.model_dump()
    profile = discovery.discover(document)
    _assert_complete(profile)
    _assert_cost(gateway, requests=29, truncated=1)
    assert document.model_dump() == original
    if not local:
        assert client.max_active == 4
    counts = Counter(record["pages"] for record in client.records if record["operation"] == "ChunkDiscovery")
    assert counts[FAILED_PAGES] == counts[(93, 94)] == counts[(95, 96)] == 1
    assert sum(counts.values()) == 26  # 24 initial blocks, two recovery requests.
    assert all(record["kwargs"]["model"] == "fixed-test-model" for record in client.records)
    for record in client.records:
        if record["pages"] in ((93, 94), (95, 96)):
            payload = record["messages"][-1]["content"]
            source = json.loads(payload.split("\n", 1)[1].rsplit("\n", 1)[0])
            fragments = source["source_fragments"]
            assert [item["source_page_start"] for item in fragments] == list(record["pages"])
            for page in record["pages"]:
                item = next(item for item in fragments if item["source_page_start"] == page)
                assert item["source_page_end"] == page
                assert item["source_char_start"] == 0
                assert item["text"] == document.pages[page - 1].text
    assert any("[PAGE 999]" in record["messages"][-1]["content"] for record in client.records if record["pages"] == (93, 94))
    failed = next(row for row in gateway.usage if row["status"] == "truncated")
    assert (failed["source_page_start"], failed["source_page_end"]) == (93, 96)
    assert failed["chunk_id"]
    assert discovery.discover(document) == profile
    assert len(client.records) == 29


def test_invalid_child_stops_then_rerun_buys_only_missing_child_and_overview(tmp_path):
    client, gateway, discovery = _setup(tmp_path, {FAILED_PAGES: ["length"], (95, 96): ["invalid", "success"]})
    document = _document()
    with pytest.raises(LLMStructuredOutputError):
        discovery.discover(document)
    _assert_cost(gateway, requests=28, truncated=1)
    assert not any(record["operation"] == "DiscoveryOverview" for record in client.records)
    boundary = len(client.records)
    profile = discovery.discover(document)
    _assert_complete(profile)
    assert [(row["operation"], row["pages"]) for row in client.records[boundary:]] == [
        ("ChunkDiscovery", (95, 96)), ("DiscoveryOverview", ()),
    ]
    _assert_cost(gateway, requests=30, truncated=1)
    assert discovery.discover(document) == profile
    assert len(client.records) == 30


def test_depth_and_shared_six_child_budget_stop_then_explicit_retry_reuses_siblings(tmp_path):
    outcomes = {pages: ["length"] for pages in (FAILED_PAGES, (93, 94), (95, 96), (96,))}
    client, gateway, discovery = _setup(tmp_path, outcomes)
    document = _document()
    with pytest.raises(LLMResponseError, match=r"(?i)(page|scope|depth|limit|bound)"):
        discovery.discover(document)
    _assert_cost(gateway, requests=32, truncated=4)
    children = [record for record in client.records if record["pages"] and set(record["pages"]) <= set(FAILED_PAGES) and record["pages"] != FAILED_PAGES]
    assert len(children) == 6
    assert Counter(record["pages"] for record in children) == Counter([(93, 94), (93,), (94,), (95, 96), (95,), (96,)])
    assert not any(record["operation"] == "DiscoveryOverview" for record in client.records)
    boundary = len(client.records)
    profile = discovery.discover(document)
    _assert_complete(profile)
    # An exhausted leaf may succeed on explicit retry; its successful siblings
    # and the known split-required parents must not be purchased again.
    assert [(row["operation"], row["pages"]) for row in client.records[boundary:]] == [
        ("ChunkDiscovery", (96,)), ("DiscoveryOverview", ()),
    ]
    _assert_cost(gateway, requests=34, truncated=4)
    assert discovery.discover(document) == profile
    assert len(client.records) == 34


@pytest.mark.parametrize("change", ["prompt", "policy"])
def test_recovery_cache_identity_changes_without_invalidating_successful_neighbors(tmp_path, monkeypatch, change):
    import adaptive_document_agent.agent.chunk_discovery_recovery as recovery

    client, gateway, discovery = _setup(tmp_path, {FAILED_PAGES: ["length", "length"]})
    document = _document()
    first = discovery.discover(document)
    assert len(client.records) == 29
    boundary = len(client.records)
    if change == "prompt":
        original_loader = recovery.load_prompt

        def changed_prompt(name):
            text = original_loader(name)
            return text + "\nUpdated recovery evidence instruction." if name == "chunk_discovery_recovery.txt" else text

        monkeypatch.setattr(recovery, "load_prompt", changed_prompt)
    else:
        monkeypatch.setattr(recovery, "RECOVERY_POLICY", recovery.RECOVERY_POLICY + "-changed")

    second = discovery.discover(document)
    assert second == first
    _assert_complete(second)
    # The old assembled root cannot bypass the updated recovery identity via
    # the ordinary chunk cache. Directly successful neighboring chunks retain it.
    added = [record["pages"] for record in client.records[boundary:]]
    assert added == ([FAILED_PAGES, (93, 94), (95, 96)] if change == "prompt" else [FAILED_PAGES])
    requests = 32 if change == "prompt" else 30
    _assert_cost(gateway, requests=requests, truncated=2)
    counts = Counter(record["pages"] for record in client.records if record["operation"] == "ChunkDiscovery")
    assert all(counts[tuple(range(start, start + 4))] == 1 for start in range(1, 93, 4))
    assert discovery.discover(document) == second
    assert len(client.records) == requests
