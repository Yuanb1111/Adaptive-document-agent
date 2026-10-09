"""Synthetic actual-orchestrator harness and introduction lifecycle regressions.

``configure_pipeline`` also runs against the pinned pre-optimization checkout:
its existing introduction already overlaps slide planning, so fixed-delay runs
measure only the added discovery-to-planning overlap, not a serial straw man.
"""

from concurrent.futures import CancelledError, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Barrier, Event, get_ident
from time import perf_counter, sleep

import pytest

from adaptive_document_agent.agent import company_introduction as introduction, orchestrator
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.models import PipelineResult, PresentationPlan, PresentationSlide, ReportPlan
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from tests.test_company_summary_pages import sample


def source_only(**kwargs):
    source = sample(**kwargs)
    # This lifecycle harness exercises generic introductory excerpts; complete
    # Summary coverage and batch reading have their own source-bound fixtures.
    for page in source.document.pages:
        page.text = page.text.replace('SUMMARY\n', '')
    company = source.presentation_plan.company.model_copy(deep=True)
    source.presentation_plan = None
    return source, company


class IntroductionClient(MockLLMClient):
    """Schema-routed evidence responses; never uses credentials or the network."""

    supports_concurrent_requests = True

    def __init__(self, company, *, delays=None, intervals=None, on_request=None):
        super().__init__()
        self.company = company
        self.delays = delays or {}
        self.intervals = intervals if intervals is not None else []
        self.on_request = on_request
        self.operations = []

    def generate_structured(self, messages, response_model, **kwargs):
        operation = response_model.__name__
        self.operations.append(operation)
        interval = {"name": operation, "started": perf_counter(), "thread": get_ident()}
        self.intervals.append(interval)
        try:
            if self.on_request:
                self.on_request(operation, messages)
            sleep(self.delays.get(operation, 0))
            if operation == "IntroductionPages":
                value = introduction.IntroductionPages(pages=[5, 18])
            elif operation == "IntroductionDraft":
                value = introduction.IntroductionDraft(overview=self.company.summary_overview,
                                                       business=self.company.summary_business)
            else:
                raise AssertionError(f"Unexpected provider request: {operation}")
            return value, LLMResponse(text=value.model_dump_json())
        finally:
            interval["finished"] = perf_counter()


@dataclass
class SyntheticPipeline:
    source: PipelineResult
    gateway: LLMGateway
    client: IntroductionClient
    intervals: list[dict] = field(default_factory=list)

    def run(self, *, progress=None):
        return orchestrator.DocumentOrchestrator(self.gateway).analyse_pdf(b"synthetic", progress=progress)


def configure_pipeline(monkeypatch, *, delays=None, local=False, concurrent=True,
                       workers=4, on_stage=None, on_request=None, source=None):
    """Instrument real orchestration while replacing unrelated work with fixed delays.

    Returned intervals use monotonic timestamps and include actual introduction
    gateway calls, candidate scoring, reporting and slide planning. Source and
    generated introductions are identical for baseline/new latency comparisons.
    """
    default_source, company = source_only()
    source = source if source is not None else default_source
    intervals = []
    delays = delays or {}
    client = IntroductionClient(company, delays=delays, intervals=intervals, on_request=on_request)
    client.supports_concurrent_requests = concurrent
    settings = LLMSettings(provider=ProviderName.OLLAMA if local else ProviderName.DEEPSEEK,
        model="synthetic", privacy_mode=PrivacyMode.LOCAL_ONLY if local else PrivacyMode.CLOUD,
        discovery_workers=workers)
    gateway = LLMGateway(client, settings)
    harness = SyntheticPipeline(source, gateway, client, intervals)

    def stage(name, value):
        interval = {"name": name, "started": perf_counter(), "thread": get_ident()}
        intervals.append(interval)
        try:
            if on_stage:
                on_stage(name, harness)
            sleep(delays.get(name, 0))
            return value
        finally:
            interval["finished"] = perf_counter()

    monkeypatch.setattr(orchestrator.DocumentOrchestrator, "_load_document", lambda *args: source.document)
    monkeypatch.setattr(orchestrator.DocumentDiscovery, "discover", lambda *args, **kwargs: source.profile)
    monkeypatch.setattr(orchestrator.TableExtractor, "extract", lambda *args, **kwargs: stage("table_extraction", {}))
    monkeypatch.setattr(orchestrator.ObservationExtractor, "extract", lambda *args, **kwargs: [])
    monkeypatch.setattr(orchestrator.SemanticResolver, "resolve_metrics", lambda *args, **kwargs: [])
    monkeypatch.setattr(orchestrator.AnalysisValueScorer, "score", lambda *args: stage("candidate_scoring", []))

    def report(self, document, profile, *args):
        return stage("reporting", PipelineResult(document=document, profile=profile,
            report_plan=ReportPlan(title="Synthetic source-bound report"), report_markdown="Evidence report"))
    monkeypatch.setattr(orchestrator.DocumentOrchestrator, "_generate_report", report)
    monkeypatch.setattr(orchestrator.PresentationPlanner, "plan", lambda *args: stage("slide_plan",
        PresentationPlan(title="Synthetic deck", slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Source overview")])) )
    monkeypatch.setattr(ExecutiveBriefWriter, "generate", lambda *args: None)
    return harness


def interval(harness, name):
    return next(row for row in harness.intervals if row["name"] == name)


def test_actual_orchestrator_starts_before_extraction_scoring_and_reporting(monkeypatch):
    started, release = Event(), Event()
    def request(operation, messages):
        if operation == "IntroductionPages":
            started.set()
            assert release.wait(3)
    def stage(name, harness):
        if name in {"table_extraction", "candidate_scoring", "reporting"}:
            assert started.wait(3), "Introduction did not start at the discovery boundary"
            assert not release.is_set()
        if name == "slide_plan":
            release.set()
    harness = configure_pipeline(monkeypatch, on_stage=stage, on_request=request)
    progress_threads = []
    result = harness.run(progress=lambda message: progress_threads.append(get_ident()))
    assert set(progress_threads) == {get_ident()}
    assert harness.client.operations == ["IntroductionPages", "IntroductionDraft"]
    assert result.presentation_plan.company.summary_business
    assert result.pipeline_total_ms >= result.stage_details_ms["company_introduction_duration"]
    assert "company_introduction_wait" in result.stage_details_ms
    assert len(result.llm_usage) == 2


@pytest.mark.parametrize("mode", ["local", "stateful", "one_worker"])
def test_actual_orchestrator_serial_modes_keep_original_request_order(monkeypatch, mode):
    harness = configure_pipeline(monkeypatch, local=mode == "local", concurrent=mode != "stateful",
                                 workers=1 if mode == "one_worker" else 4)
    result = harness.run()
    assert interval(harness, "IntroductionPages")["started"] >= interval(harness, "slide_plan")["finished"]
    assert {row["thread"] for row in harness.intervals} == {get_ident()}
    assert result.presentation_plan.company.summary_business


def test_snapshot_is_independent_of_table_and_profile_mutations(monkeypatch):
    source, expected = source_only()
    started, release = Event(), Event()
    def generate(gateway, snapshot, draft, **kwargs):
        started.set()
        assert release.wait(3)
        assert snapshot.document.pages[1].text == "OVERVIEW\nWe operate a business software platform."
        assert snapshot.profile.document_summary_pages == []
        assert not snapshot.document.pages[1].tables
        draft.company = expected
    monkeypatch.setattr(introduction, "ensure_company_introduction", generate)
    from tests.test_ppt_generation_performance import gateway
    with introduction.prepare_company_introduction(gateway(), source) as attach:
        assert started.wait(3)
        source.document.pages[1].text = "Mutated"
        source.profile.document_summary_pages = [30]
        release.set()
        with pytest.raises(ValueError, match="no longer matches"):
            attach(PresentationPlan(title="Deck"))


def test_final_rebound_planning_source_is_used_in_actual_orchestrator(monkeypatch):
    harness = configure_pipeline(monkeypatch)
    replaced = harness.source.document.model_copy(deep=True)
    replaced.pages[1].text = "Rebound source with no supporting quote"
    class TableCache:
        def get_model(self, key, model):
            return replaced if key.startswith("tables-") else None
        def set_model(self, *args):
            pass
    result = orchestrator.DocumentOrchestrator(harness.gateway, cache=TableCache()).analyse_pdf(b"synthetic")
    assert result.document is replaced
    assert result.presentation_plan.company.summary_overview is None
    assert any(issue.code == "company_introduction_unavailable" for issue in result.validation_warnings)
    assert harness.client.operations == ["IntroductionPages", "IntroductionDraft"]


@pytest.mark.parametrize("background", [False, True])
def test_failed_draft_and_successful_repeated_attach_make_no_duplicate_requests(background):
    source, company = source_only()
    client = IntroductionClient(company)
    client.supports_concurrent_requests = background
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.DEEPSEEK))
    with introduction.prepare_company_introduction(gateway, source) as attach:
        first, second = PresentationPlan(title="First"), PresentationPlan(title="Second")
        attach(first)
        attach(first)
        attach(second)
        assert first.company == second.company
        assert first.company is not second.company
    assert client.operations == ["IntroductionPages", "IntroductionDraft"]

    def fail(operation, messages):
        raise ValueError("Synthetic unavailable response")
    client.on_request = fail
    client.operations.clear()
    with introduction.prepare_company_introduction(gateway, source) as attach:
        for _ in range(2):
            with pytest.raises(ValueError, match="unavailable"):
                attach(PresentationPlan(title="Empty"))
    assert client.operations == ["IntroductionPages"]


def test_already_verified_introduction_requires_no_provider_requests():
    source = sample()
    client = IntroductionClient(source.presentation_plan.company)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.DEEPSEEK))
    with introduction.prepare_company_introduction(gateway, source) as attach:
        attach(source.presentation_plan)
        attach(PresentationPlan(title="Another"))
    assert client.operations == []


@pytest.mark.parametrize("operation", ["IntroductionPages", "IntroductionDraft"])
def test_primary_failure_cancels_worker_before_next_call_and_drains_usage(monkeypatch, operation):
    started, release, cancellation_seen = Event(), Event(), Event()
    close = introduction.PreparedCompanyIntroduction.close
    def track_close(self):
        self._cancelled.set()
        cancellation_seen.set()
        release.set()
        return close(self)
    monkeypatch.setattr(introduction.PreparedCompanyIntroduction, "close", track_close)
    def request(name, messages):
        if name == operation:
            started.set()
            assert release.wait(3)
    def stage(name, harness):
        if name == "candidate_scoring":
            assert started.wait(3)
            raise RuntimeError("Primary scoring failure")
    harness = configure_pipeline(monkeypatch, on_stage=stage, on_request=request)
    with pytest.raises(RuntimeError, match="Primary scoring failure"):
        harness.run()
    assert cancellation_seen.is_set()
    assert all("finished" in row for row in harness.intervals)
    assert harness.client.operations == (["IntroductionPages"] if operation == "IntroductionPages"
                                         else ["IntroductionPages", "IntroductionDraft"])
    assert len(harness.gateway.usage) == len(harness.client.operations)


def test_late_cancellation_cannot_turn_completed_draft_into_success():
    source, company = source_only()
    client = IntroductionClient(company)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.DEEPSEEK))
    with introduction.prepare_company_introduction(gateway, source) as attach:
        attach._future.result(timeout=3)
        attach.close()
        plan = PresentationPlan(title="Cancelled")
        with pytest.raises(CancelledError):
            attach(plan)
        assert plan.company.summary_overview is None


def test_worker_cannot_attach_or_mutate_final_plan():
    source, company = source_only()
    gateway = LLMGateway(IntroductionClient(company), LLMSettings(provider=ProviderName.DEEPSEEK))
    with introduction.prepare_company_introduction(gateway, source) as attach:
        plan = PresentationPlan(title="Deck")
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(RuntimeError, match="pipeline caller"):
                pool.submit(attach, plan).result(timeout=3)
        assert plan.company.summary_overview is None
        attach(plan)


def test_simultaneous_sessions_do_not_share_sources_results_or_cancellation():
    barrier = Barrier(2)
    def session(claim, fail):
        source, company = source_only(claim=claim)
        source.document.sha256 = claim
        def request(operation, messages):
            if operation == "IntroductionPages":
                barrier.wait(timeout=3)
        client = IntroductionClient(company, on_request=request)
        gateway = LLMGateway(client, LLMSettings(provider=ProviderName.DEEPSEEK))
        with introduction.prepare_company_introduction(gateway, source) as attach:
            if fail:
                attach._future.result(timeout=3)
                attach.close()
                with pytest.raises(CancelledError):
                    attach(PresentationPlan(title="Cancelled"))
                return None
            plan = PresentationPlan(title="Successful")
            attach(plan)
            return plan.company.summary_business.items[0].text
    with ThreadPoolExecutor(max_workers=2) as pool:
        failed = pool.submit(session, "We supply industrial equipment.", True)
        success = pool.submit(session, "We operate a distribution platform.", False)
        assert failed.result(timeout=3) is None
        assert success.result(timeout=3) == "We operate a distribution platform."


def test_missing_final_plan_drains_inflight_request_before_complete_and_usage(monkeypatch):
    started, release = Event(), Event()
    close = introduction.PreparedCompanyIntroduction.close
    def close_and_release(self):
        self._cancelled.set()
        release.set()
        return close(self)
    monkeypatch.setattr(introduction.PreparedCompanyIntroduction, "close", close_and_release)
    def request(name, messages):
        if name == "IntroductionPages":
            started.set()
            assert release.wait(3)
    harness = configure_pipeline(monkeypatch, on_request=request)
    def no_plan(*args):
        assert started.wait(3)
        return None
    monkeypatch.setattr(orchestrator.PresentationPlanner, "plan", no_plan)
    def progress(message):
        if message == "Complete":
            assert all("finished" in row for row in harness.intervals)
            assert len(harness.gateway.usage) == 1
    def brief(self, result):
        assert release.is_set(), "Unused introduction must be cancelled before executive briefing"
        assert all("finished" in row for row in harness.intervals)
        assert harness.client.operations == ["IntroductionPages"]
        return None
    monkeypatch.setattr(ExecutiveBriefWriter, "generate", brief)
    result = harness.run(progress=progress)
    assert result.presentation_plan is None
    assert len(result.llm_usage) == 1
    assert harness.client.operations == ["IntroductionPages"]
    assert result.pipeline_total_ms >= result.stage_details_ms["company_introduction_duration"]


def test_valid_final_plan_skips_serial_requests(monkeypatch):
    harness = configure_pipeline(monkeypatch, concurrent=False)
    monkeypatch.setattr(orchestrator.PresentationPlanner, "plan", lambda *args: sample().presentation_plan)
    result = harness.run()
    assert result.presentation_plan.company.summary_business
    assert harness.client.operations == []


def test_source_ownership_is_checked_even_if_introduction_quotes_happen_to_match():
    source, company = source_only()
    other = source.model_copy(deep=True)
    other.document.sha256 = "another-upload"
    gateway = LLMGateway(IntroductionClient(company), LLMSettings(provider=ProviderName.DEEPSEEK))
    with introduction.prepare_company_introduction(gateway, source) as attach:
        with pytest.raises(ValueError, match="another source document"):
            attach(PresentationPlan(title="Deck"), other)


@pytest.mark.parametrize("workers", [2, 4])
def test_early_intro_and_semantic_batches_share_actual_gateway_capacity(monkeypatch, workers):
    from threading import Lock
    from tests.test_llm_request_admission import Answer

    harness = configure_pipeline(monkeypatch, workers=workers)
    lock, intro_started, capacity_reached, release = Lock(), Event(), Event(), Event()
    active = maximum = 0
    generate = harness.client.generate_structured
    def counted(messages, response_model, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == workers:
                capacity_reached.set()
        try:
            if response_model is introduction.IntroductionPages:
                intro_started.set()
            assert release.wait(3)
            if response_model is Answer:
                return Answer(), LLMResponse(text='{"value":1}')
            return generate(messages, response_model, **kwargs)
        finally:
            with lock:
                active -= 1
    harness.client.generate_structured = counted
    def semantic(self, metrics, **kwargs):
        assert intro_started.wait(3)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(harness.gateway.generate_structured, [], Answer, stage="semantic")
                       for _ in range(4)]
            try:
                assert capacity_reached.wait(3)
                # Give all four contenders an opportunity to enter their calls.
                sleep(.02)
                assert active == workers
            finally:
                release.set()
            for future in futures:
                future.result(timeout=3)
        return []
    monkeypatch.setattr(orchestrator.SemanticResolver, "resolve_metrics", semantic)
    result = harness.run()
    assert maximum == workers
    assert active == 0
    assert result.presentation_plan.company.summary_business
    assert len(result.llm_usage) == 6
