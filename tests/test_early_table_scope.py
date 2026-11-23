from threading import Event
from types import SimpleNamespace

from adaptive_document_agent.agent import orchestrator, report_requirements, source_coverage
from adaptive_document_agent.agent.document_discovery import ChunkDiscovery, DiscoveryOverview, DocumentDiscovery
from adaptive_document_agent.models import AnalysisPageRange
from tests.test_early_company_introduction import configure_pipeline
from tests.test_source_coverage import sample


def test_discovery_exposes_final_scope_after_supplementary_checks(monkeypatch):
    document, ranges = sample()
    additional = AnalysisPageRange(title='Conditions', start_page=5, end_page=6, reason='Source check')
    final_ranges = [*ranges, additional]
    ledger = source_coverage.section_ledger(document, final_ranges)
    discovery = DocumentDiscovery(SimpleNamespace())
    ready = []

    def discover_chunks(chunks, _notify):
        assert ready == [final_ranges]
        return [ChunkDiscovery(summary='Source summary') for _ in chunks]

    monkeypatch.setattr(source_coverage, 'check_source_scope', lambda *a, **k: (final_ranges, ledger))
    monkeypatch.setattr(discovery, '_discover_chunks', discover_chunks)
    monkeypatch.setattr(discovery, '_synthesize_overview', lambda *a: DiscoveryOverview())

    profile = discovery.discover(document, routed_ranges=ranges, enable_source_checks=True,
                                 on_scope_selected=ready.append)

    assert profile.analysis_page_ranges == [(1, 3), (5, 6)]
    assert profile.source_coverage == ledger


def test_pipeline_extracts_final_ranges_and_appendix_while_discovery_is_active(monkeypatch):
    harness = configure_pipeline(monkeypatch)
    selected = AnalysisPageRange(title='Current scope', start_page=5, end_page=5, reason='Source route')
    started, release = Event(), Event()
    scopes = []

    def extract(_self, _pdf, *, page_numbers):
        scopes.append(page_numbers)
        started.set()
        assert release.wait(5)
        return {number: [] for number in page_numbers}

    def discover(_self, document, *, on_scope_selected, **_kwargs):
        on_scope_selected([selected])
        try:
            assert started.wait(5)
            assert all(page.table_extraction_status != 'processed' for page in document.pages)
        finally:
            release.set()
        return harness.source.profile.model_copy(update={'analysis_page_ranges': [(5, 5)]})

    monkeypatch.setattr(report_requirements, 'appendix_pages', lambda _requirements: {18})
    monkeypatch.setattr(orchestrator.TableExtractor, 'extract', extract)
    monkeypatch.setattr(orchestrator.DocumentDiscovery, 'discover', discover)

    result = harness.run()

    assert scopes == [{5, 18}]
    assert {page.page_number for page in result.document.pages
            if page.table_extraction_status == 'processed'} == {5, 18}
