"""Regression boundaries for failed exports, source scopes and partial retries."""
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest

from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
from adaptive_document_agent.agent.executor import AnalysisExecutor
from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.document_model.series import metric_key, canonical_series_partition_key
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.pdf_parser import PDFParser, PDFValidationError
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.models import DocumentPage, DocumentProfile, ParsedDocument, PipelineResult, ValidationIssue
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from adaptive_document_agent.models.summary import SummaryPart, SummaryReview, SummarySourceBlock
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName, PrivacyMode
from adaptive_document_agent.services.pipeline_completion import is_complete
from adaptive_document_agent.services.summary_validation import reading_errors
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
from tests.test_p0_composition import observation
from tests.test_failed_analysis_reruns import flow


def source_result(text='Source passage.'):
    return PipelineResult(document=ParsedDocument(document_id='d', sha256='hash', safe_filename='d.pdf',
        page_count=1, pages=[DocumentPage(page_number=1, text=text)]), profile=DocumentProfile())


def test_date_translation_keeps_exact_calendar_evidence_and_rejects_changed_dates():
    quote = 'As at December 31, 2021, 2022 and 2023 and June 30, 2024, assets are stated in RMB thousands.'
    result = source_result(quote)
    item = ExecutiveBriefItem(label='Dates', text='截至2021年、2022年、2023年12月31日及2024年6月30日，资产以人民币千元列示。',
                              evidence=[BriefQuote(page=1, text=quote)])
    brief = ExecutiveBrief(title='Dates', items=[item])
    assert not validate_executive_brief(brief, result)
    item.text = item.text.replace('6月30日', '7月30日')
    assert any('calendar:07-30' in e for e in validate_executive_brief(brief, result))


def test_capacity_and_actual_output_cannot_share_canonical_series_or_trend():
    capacity = observation('a', 'Production capacity (units)', 100, 'FY2023', unit='count')
    output = observation('b', 'Production output (units)', 80, 'FY2024', unit='count')
    capacity.metric_canonical = output.metric_canonical = 'production'
    assert metric_key(capacity) != metric_key(output)
    assert canonical_series_partition_key(capacity) != canonical_series_partition_key(output)
    task = SimpleNamespace(tool_name='percentage_change', analysis_type='percentage_change', required_dimensions=[])
    with pytest.raises(ValueError, match='different source metrics'):
        AnalysisExecutor._validate_reporting_scope([capacity, output], task)


def test_explicit_group_company_headers_bind_reporting_scope_without_changing_metric():
    table = ExtractedTable(table_id='t', page=1, headers=['Metric', 'Group 2023', 'Group 2024', 'Company 2023', 'Company 2024'],
        column_periods=[None, '2023', '2024', '2023', '2024'],
        rows=[TableRow(cells=['Revenue', '100', '110', '60', '70'], page=1)])
    items = ObservationExtractor()._table_observations(table)
    assert [o.entity for o in items] == ['Group', 'Group', 'Company', 'Company']
    assert all(o.metric_original == 'Revenue' for o in items)
    assert canonical_series_partition_key(items[0]) != canonical_series_partition_key(items[2])
    task = SimpleNamespace(tool_name='ratio', analysis_type='ratio', required_dimensions=[])
    with pytest.raises(ValueError, match='reporting scopes'):
        AnalysisExecutor._validate_reporting_scope([items[0], items[2]], task)


def test_short_important_paragraph_cannot_be_hidden_as_layout():
    text = 'No dividends were declared.\n'
    result = source_result(text)
    block = SummarySourceBlock(id='s', page=1, char_start=0, char_end=len(text), text=text)
    part = SummaryPart(id='p', block_id='s', start_line=1, end_line=1, source_page=1,
        source_text=text, title='Footer', reading_note='Layout', role='layout')
    review = SummaryReview(document_id='d', document_sha256='hash', source_pages=[1], source_blocks=[block], parts=[part])
    assert any('Nonblank layout' in e for e in reading_errors(review, result, complete_scope=False))


def test_noncomparative_brief_claim_is_independently_reviewed_and_unchanged_success_is_memoized():
    quote = 'Reported production capacity was 100 units.'
    result = source_result(quote)
    brief = ExecutiveBrief(title='Capacity', items=[ExecutiveBriefItem(label='Production',
        text='Production output was 100 units.', evidence=[BriefQuote(page=1, text=quote)])])
    gateway = Mock()
    from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview
    gateway.generate_structured.return_value = BriefMeaningReview(items=[dict(index=0, accepted=False,
        reason='Capacity is not actual output', numeric_comparison=False, comparisons=[])])
    check = meaning_validator(gateway, result=result)
    assert 'Capacity' in str(check(brief))
    assert check(brief)
    assert gateway.generate_structured.call_count == 1


def test_encrypted_pdf_is_blocked_before_discovery_including_legacy_cached_metadata(tmp_path):
    pdf = pymupdf.open(); pdf.new_page()
    raw = pdf.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='password'); pdf.close()
    with pytest.raises(PDFValidationError, match='encrypted'):
        PDFParser().parse(raw)
    cache = DiskCache(tmp_path)
    digest = sha256_bytes(raw)
    cache.set_model('document-v4-' + digest, ParsedDocument(document_id='d', sha256=digest,
        safe_filename='d.pdf', page_count=1, encrypted=True))
    gateway = Mock()
    with pytest.raises(PDFValidationError, match='encrypted'):
        DocumentOrchestrator(gateway, cache=cache).preview_scope(raw)
    gateway.generate_structured.assert_not_called()


@pytest.mark.parametrize('failure_stage', ['extraction', 'cleanup'])
def test_one_failed_table_page_does_not_skip_later_pages(monkeypatch, failure_stage):
    import pdfplumber
    from adaptive_document_agent.extraction import borderless_table_extractor, source_grid_recovery, table_footnotes
    pages = [Mock(bbox=(0, 0, 100, 100), cropbox=None) for _ in range(3)]
    for page in pages:
        page.find_tables.return_value = []
    if failure_stage == 'extraction':
        pages[1].find_tables.side_effect = ValueError('Broken table geometry')
    else:
        pages[1].close.side_effect = ValueError('Broken page cleanup')
    monkeypatch.setattr(pdfplumber, 'open', lambda *a, **k: nullcontext(SimpleNamespace(pages=pages)))
    monkeypatch.setattr(borderless_table_extractor.BorderlessTableExtractor, 'extract', lambda *a: [])
    monkeypatch.setattr(source_grid_recovery, 'recover_source_grids', lambda *a, **k: [])
    monkeypatch.setattr(table_footnotes, 'retain_table_footnotes', lambda *a: None)
    extractor = TableExtractor()
    assert extractor.extract(b'invalid geometry input') == {1: [], 3: []}
    assert extractor.page_errors == {2: 'ValueError'}
    assert extractor.source_inventory_by_page[2]['status'] == 'failed'
    assert all(p.close.call_count == 1 for p in pages)


def test_failed_semantic_stage_discards_its_requests_but_keeps_successful_stage_cache(tmp_path):
    from pydantic import BaseModel
    class Draft(BaseModel):
        text: str
    client = MockLLMClient([{'text': 'verified'}, {'text': 'wrong'}, {'text': 'corrected'}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model='offline', privacy_mode=PrivacyMode.LOCAL_ONLY), cache=DiskCache(tmp_path))
    good, bad = [{'role': 'user', 'content': 'good'}], [{'role': 'user', 'content': 'bad'}]
    with gateway.validated_cache_scope():
        assert gateway.generate_structured(good, Draft, stage='presentation').text == 'verified'
    with pytest.raises(ValueError), gateway.validated_cache_scope():
        gateway.generate_structured(bad, Draft, stage='presentation')
        raise ValueError('Semantic rejection')
    with gateway.validated_cache_scope():
        assert gateway.generate_structured(good, Draft, stage='presentation').text == 'verified'
        assert gateway.generate_structured(bad, Draft, stage='presentation').text == 'corrected'
    assert len(client.calls) == 3


def test_failed_introduction_is_partial_even_for_legacy_results():
    result = source_result()
    result.validation_warnings.append(ValidationIssue(code='company_introduction_unavailable', message='Failed', stage='presentation'))
    assert not is_complete(result)


def test_date_axis_labels_keep_each_scaled_count_unit():
    from adaptive_document_agent.models import ChartPlan
    from adaptive_document_agent.services.pptx_export import _add_native_chart
    from tests.test_presentation_brief import blank_deck
    items = [observation(str(i), 'Units held', v, p, unit='count')
        for i, (p, v) in enumerate([('2023-12-31', 1234567), ('2024-06-30', 1234568)])]
    for item in items:
        item.period_type, item.as_of_date, item.unit_family = 'balance_sheet_date', item.period, 'count'
    deck = blank_deck(); slide = deck.slides.add_slide(deck.slide_layouts[6])
    _add_native_chart(slide, ChartPlan(id='c', question='Counts', chart_type='line', title='Units held'), items, (.5, 1, 6, 4))
    chart = next(s.chart for s in slide.shapes if s.has_chart)
    copy = [p.text for p in chart._chartSpace.xpath('.//c:dLbl//a:t')]
    assert len(set(copy)) == 2
    assert any('1.234567' in text or '1,234.567' in text for text in copy)
    assert any('1.234568' in text or '1,234.568' in text for text in copy)


def test_partial_result_has_retry_state_and_is_never_cached_as_complete(flow):
    from adaptive_document_agent.ui import app
    flow.result.pipeline_version = PIPELINE_VERSION
    flow.result.pipeline_state, flow.result.retry_from = 'partial', 'reporting'
    success = flow.result.model_copy(update={'pipeline_state': 'complete', 'retry_from': None})
    flow.outcomes.clear(); flow.outcomes.extend([flow.result, success])
    key = app._analysis_scope_key(b'first-pdf', '', flow.settings)
    options = dict(scope_key=key, analysis_focus='', settings=flow.settings, cache=flow.cache)
    assert app._analyse_upload(flow.st, b'first-pdf', **options) is flow.result
    assert flow.st.session_state['analysis_attempts'][key]['state'] == 'partial'
    assert 'analysis-result-' + key not in flow.cache.values
    assert app._analyse_upload(flow.st, b'first-pdf', **options) is flow.result
    assert len(flow.attempts) == 1
    assert app._analyse_upload(flow.st, b'first-pdf', retry=True, **options) is success
    assert flow.st.session_state['analysis_attempts'][key]['state'] == 'complete'
    assert flow.cache.values['analysis-result-' + key] is success


def test_reanalyse_does_not_take_another_scope_keys_preview(flow):
    from adaptive_document_agent.ui import app
    from adaptive_document_agent.services.presentation_requirements import budget_request, fixed_presentation_budget
    key = app._analysis_scope_key(b'first-pdf', budget_request('', fixed_presentation_budget()), flow.settings)
    flow.st.session_state.update(analysis_result=flow.result, analysis_result_key=key,
        analysis_scope=flow.preview, analysis_scope_key='another-document-or-focus')
    flow.st.toggle.return_value = True
    flow.outcomes.clear(); flow.outcomes.append(flow.result)
    flow.pressed.add('Reanalyse PDF (ignore model cache)')
    app.run_app()
    assert len(flow.attempts) == 1 and flow.attempts[0]['scope'] is None


def test_reporting_retry_skips_discovery_semantics_scoring_and_calculation(monkeypatch):
    from adaptive_document_agent.agent import orchestrator as module, company_introduction
    from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget, fixed_presentation_budget
    raw = b'checkpoint source'
    result = source_result()
    result.profile.report_requirements = apply_presentation_budget(None, '', fixed_presentation_budget())
    result.document.sha256 = sha256_bytes(raw)
    result.pipeline_version, result.pipeline_state, result.retry_from = PIPELINE_VERSION, 'partial', 'reporting'
    gateway = SimpleNamespace(cache=None, discovery_workers=1, usage=[])
    runner = DocumentOrchestrator(gateway)
    monkeypatch.setattr(runner, '_load_document', lambda *a: result.document)
    monkeypatch.setattr(company_introduction, 'prepare_company_introduction',
        lambda *a, **k: nullcontext(SimpleNamespace(failed=lambda: False, raise_if_failed=lambda: None)))
    discover, score, execute = Mock(side_effect=AssertionError('Discovery must be reused')), Mock(), Mock()
    monkeypatch.setattr(module.DocumentDiscovery, 'discover', discover)
    monkeypatch.setattr(module.AnalysisValueScorer, 'score', score)
    monkeypatch.setattr(module.AnalysisExecutor, 'execute', execute)
    monkeypatch.setattr(runner, '_generate_report', Mock(side_effect=ValueError('Reached resumed reporting')))
    with pytest.raises(ValueError, match='Reached resumed reporting'):
        runner.analyse_pdf(raw, resume=result)
    discover.assert_not_called(); score.assert_not_called(); execute.assert_not_called()


def test_partial_table_extraction_is_not_written_to_completed_table_cache(tmp_path, monkeypatch):
    from adaptive_document_agent.agent import orchestrator as module
    raw = b'source'
    document = ParsedDocument(document_id='d', sha256=sha256_bytes(raw), safe_filename='d.pdf', page_count=3,
        pages=[DocumentPage(page_number=i, text='Source') for i in range(1, 4)])
    cache = DiskCache(tmp_path)
    runner = DocumentOrchestrator(cache=cache)
    monkeypatch.setattr(runner, '_load_document', lambda *a: document)
    monkeypatch.setattr(module.DocumentDiscovery, 'discover', lambda *a, **k: DocumentProfile())
    monkeypatch.setattr(module.TableExtractor, 'extract', lambda *a, **k: {1: [], 3: []})
    result = runner.analyse_pdf(raw)
    assert [p.table_extraction_status for p in result.document.pages] == ['processed', 'failed', 'processed']
    assert not list(tmp_path.glob('tables-*.json'))
    assert result.pipeline_state == 'partial'


def test_verified_themes_are_reused_after_another_theme_fails(tmp_path):
    from tests.test_summary_themes_v118 import Themes
    from tests.test_compact_summary_v111 import fixture
    from adaptive_document_agent.agent.summary_themes import generate_thematic_summary
    from adaptive_document_agent.models.presentation import CompanyProfile
    class CachedThemes(Themes):
        discovery_workers = 1
        cache_enabled = True
        settings = LLMSettings(provider=ProviderName.MOCK, model='offline')
        client = MockLLMClient()
    gateway = CachedThemes(reject='part-15')
    gateway.cache = DiskCache(tmp_path)
    result, review, _ = fixture(20)
    review.max_intro_slides = None
    with pytest.raises(ValueError):
        generate_thematic_summary(gateway, result, review, CompanyProfile(summary_review=review))
    assert len(list(tmp_path.glob('verified-summary-theme-*.json'))) == 1
    first_count = gateway.calls.count('CompactSummaryDraft')
    gateway.reject = None
    retried = review.model_copy(update={'plan_audits': [], 'decisions': [], 'timings_ms': {}})
    company = generate_thematic_summary(gateway, result, retried, CompanyProfile(summary_review=retried))
    assert company.summary_pages
    assert gateway.calls.count('CompactSummaryDraft') == first_count + 1


def test_resolver_keeps_original_when_mapping_erases_capacity_or_turns_output_into_capacity():
    from adaptive_document_agent.agent.semantic_resolver import SemanticResolver
    client = MockLLMClient([{'mappings': [
        dict(original_name='Production capacity (units)', canonical_name='production', confidence=.95),
        dict(original_name='Production output (units)', canonical_name='production capacity', confidence=.95)]}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model='offline'))
    mappings = SemanticResolver(gateway).resolve_metrics(['Production capacity (units)', 'Production output (units)'])
    assert all(m.canonical_name is None for m in mappings)


def test_merged_group_company_header_inherits_only_declared_column_spans():
    table = ExtractedTable(table_id='merged', page=1, headers=['Metric', '2023', '2024', '2023', '2024'],
        column_periods=[None, '2023', '2024', '2023', '2024'],
        raw_header_cells=[['Metric', 'Group', None, 'Company', None]],
        raw_header_spans=[(0, 1, 2), (0, 3, 4)],
        rows=[TableRow(page=1, cells=['Revenue', '100', '110', '60', '70'])])
    assert [o.entity for o in ObservationExtractor()._table_observations(table)] == ['Group', 'Group', 'Company', 'Company']


def test_failed_reading_response_cache_is_revoked_before_local_retry(tmp_path):
    from threading import Event
    from adaptive_document_agent.agent.summary_reader import _read_batch
    text = 'No dividends were declared.'
    result = source_result(text)
    block = SummarySourceBlock(id='b', page=1, char_start=0, char_end=len(text), text=text)
    bad = {'parts': [dict(block_id='b', start_line=1, end_line=1, title='Layout',
        role='layout', reading_note='Treat as layout', facts=[])]}
    good = {'parts': [dict(block_id='b', start_line=1, end_line=1, title='Dividends',
        role='content', reading_note='A substantive dividend disclosure', facts=[dict(
            label='Dividends', text=text, quote_start_line=1, quote_end_line=1)])]}
    # Exhaust both full readings and both bounded layout rereads before the
    # separate local retry supplies a valid substantive-content decision.
    client = MockLLMClient([bad, bad, bad, bad, good])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model='offline'), cache=DiskCache(tmp_path))
    first = _read_batch(gateway, result, [block], Event())
    assert first.error is not None and not list(tmp_path.glob('llm-*.json'))
    assert len(client.calls) == 4
    retried = _read_batch(gateway, result, [block], Event())
    assert retried.error is None and retried.parts[0].role == 'content'
    assert len(client.calls) == 5


def test_explicit_group_company_row_labels_remain_different_scopes_after_metric_mapping():
    table = ExtractedTable(table_id='entities', page=1, headers=['Metric', '2023', '2024'],
        column_periods=[None, '2023', '2024'], table_title='Revenue',
        rows=[TableRow(page=1, cells=['Group', '100', '110']),
              TableRow(page=1, cells=['Company', '60', '70'])])
    items = ObservationExtractor()._table_observations(table)
    for item in items:
        item.metric_canonical = 'Revenue'
    assert [o.entity for o in items] == ['Group', 'Group', 'Company', 'Company']
    assert canonical_series_partition_key(items[0]) != canonical_series_partition_key(items[2])
    assert items[0].raw_value == '100' and items[2].raw_value == '60'
