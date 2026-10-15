from adaptive_document_agent.services.presentation_requirements import budget_request, fixed_presentation_budget


def test_fixed_slide_limits_are_part_of_the_actual_upload_request(monkeypatch):
    from types import SimpleNamespace
    from tests.test_streamlit_auto_flow import _Streamlit
    from adaptive_document_agent.ui import app as ui_app
    from adaptive_document_agent.models import PipelineResult, ParsedDocument, DocumentProfile
    from adaptive_document_agent.models.customization import PresentationBudget
    result = PipelineResult(document=ParsedDocument(document_id='d', sha256='h',
        safe_filename='d.pdf', page_count=1), profile=DocumentProfile())
    captured = []
    class Orchestrator:
        def __init__(self, *args, **kwargs): pass
        def analyse_pdf(self, raw, **kwargs):
            assert kwargs['presentation_budget'].body_slides == 20
            assert kwargs['presentation_budget'].introduction_slides == 5
            captured.append(kwargs['analysis_focus'])
            return result
    monkeypatch.setattr(ui_app, 'DocumentOrchestrator', Orchestrator)
    monkeypatch.setattr(ui_app, 'create_llm_client', lambda settings: None)
    monkeypatch.setattr(ui_app, 'LLMGateway', lambda *args, **kwargs: SimpleNamespace(usage=[]))
    monkeypatch.setattr(ui_app, '_start_analysis_worker', lambda target: target())
    from adaptive_document_agent.services.llm.config import LLMSettings
    instruction = budget_request('Keep scope and reporting periods separate.', fixed_presentation_budget())
    ui_app._analyse_upload(_Streamlit(), b'%PDF', scope_key='limits', analysis_focus=instruction,
        settings=LLMSettings(model='mock'), cache=None,
        presentation_budget=PresentationBudget(body_slides=20, introduction_slides=5))
    assert captured == [instruction]
    assert 'at most 20 physical slides' in instruction
    assert 'at most 5 physical slides' in instruction
    assert 'Data Index source-reference and literal source-table pages are counted separately' in instruction
    assert 'Keep scope and reporting periods separate.' in instruction
    assert instruction != budget_request('', fixed_presentation_budget())


def test_introduction_limit_cannot_exceed_whole_body_limit():
    from adaptive_document_agent.models.customization import PresentationBudget
    assert 'introduction must contain at most 3' in budget_request('',
        fixed_presentation_budget(PresentationBudget(body_slides=3, introduction_slides=5)))


def test_real_upload_has_no_page_controls_and_always_carries_fixed_limits():
    from tests.test_streamlit_startup import run_fresh
    run_fresh('''
        from types import SimpleNamespace
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        calls = []
        def capture(st, raw, **kwargs):
            calls.append((raw, kwargs['presentation_budget'], kwargs['scope_key'], kwargs['analysis_focus']))
        probe = {'ready': True, 'backend': 'test', 'message': ''}
        with patch('streamlit.file_uploader', return_value=SimpleNamespace(getvalue=lambda: b'%PDF-test')), \\
             patch('adaptive_document_agent.services.export_readiness.check_export_readiness', return_value=probe), \\
             patch('adaptive_document_agent.ui.app._analyse_upload', side_effect=capture):
            app = AppTest.from_file('app.py', default_timeout=30).run()
            assert not app.exception, app.exception
            assert calls[-1][0] == b'%PDF-test'
            assert calls[-1][1].body_slides == 20
            assert calls[-1][1].introduction_slides == 5
            assert calls[-1][1].slide_scope == 'body'
            assert calls[-1][3] == ''
            first = calls[-1][2]
            labels = {item.label for item in app.number_input}
            assert 'Maximum PPT slides' not in labels
            assert 'Maximum introduction slides' not in labels
            assert 'Count appendices separately' not in {item.label for item in app.checkbox}
            # Stale session values from an older release cannot change policy.
            app.session_state['body_slide_limit'] = 100
            app.session_state['introduction_slide_limit'] = 50
            app.run()
            assert not app.exception, app.exception
            assert calls[-1][1].body_slides == 20
            assert calls[-1][1].introduction_slides == 5
            assert calls[-1][1].slide_scope == 'body'
            assert calls[-1][2] == first
            app.text_area[0].input('Focus on source-supported risks.').run()
            assert not app.exception, app.exception
            assert calls[-1][3] == 'Focus on source-supported risks.'
            assert calls[-1][2] != first
    ''')


def test_explicit_budget_survives_failed_free_text_interpretation():
    from adaptive_document_agent.models.customization import PresentationBudget, ReportRequirements
    from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget
    from adaptive_document_agent.services.slide_budgets import resolved_limits
    from adaptive_document_agent.agent.report_requirements import validate_requirements
    from adaptive_document_agent.models import ParsedDocument
    failed = ReportRequirements(original_request='Explain key risks.', interpretation_error='Invalid model response')
    bound = apply_presentation_budget(failed, failed.original_request,
        PresentationBudget(body_slides=20, introduction_slides=5))
    assert bound.interpretation_error == failed.interpretation_error
    assert not failed.items
    assert resolved_limits(bound, section='report', scope='all') == [20]
    assert resolved_limits(bound, section='introduction', scope='all') == [5]
    assert not validate_requirements(bound, ParsedDocument(document_id='d', sha256='h',
        safe_filename='d.pdf', page_count=1), bound.original_request)


def test_orchestrator_binds_fixed_limits_without_ui_settings(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from adaptive_document_agent.agent import orchestrator, company_introduction
    from adaptive_document_agent.models import DocumentProfile, ParsedDocument
    from adaptive_document_agent.models.customization import PresentationBudget
    from adaptive_document_agent.services.slide_budgets import resolved_limits
    runner = orchestrator.DocumentOrchestrator(SimpleNamespace(discovery_workers=2, cache=None))
    document = ParsedDocument(document_id='d', sha256='h', safe_filename='d.pdf', page_count=1)
    monkeypatch.setattr(runner, '_load_document', lambda *args: document)
    monkeypatch.setattr(orchestrator.DocumentDiscovery, 'discover', lambda *args, **kwargs: DocumentProfile())
    def prepared(gateway, result, **kwargs):
        assert resolved_limits(result.profile.report_requirements, section='report', scope='body') == [20]
        assert resolved_limits(result.profile.report_requirements, section='introduction', scope='body') == [5]
        raise RuntimeError('Reached introduction with explicit budgets')
    monkeypatch.setattr(company_introduction, 'prepare_company_introduction', prepared)
    with pytest.raises(RuntimeError, match='Reached introduction with explicit budgets'):
        runner.analyse_pdf(b'source')


def test_callers_can_only_tighten_fixed_limits():
    from adaptive_document_agent.models.customization import PresentationBudget
    requested = PresentationBudget(body_slides=100, introduction_slides=30,
                                   analysis_slides=50, slide_scope='body')
    actual = fixed_presentation_budget(requested)
    assert (actual.body_slides, actual.introduction_slides, actual.analysis_slides, actual.slide_scope) == (20, 5, 10, 'body')
    assert requested.body_slides == 100
    tighter = fixed_presentation_budget(PresentationBudget(body_slides=18, introduction_slides=3, analysis_slides=6))
    assert (tighter.body_slides, tighter.introduction_slides, tighter.analysis_slides) == (18, 3, 6)


def test_presentation_system_prompt_has_fixed_policy_even_without_custom_instructions():
    from adaptive_document_agent.agent.prompting import with_presentation_limits
    policy = with_presentation_limits('Plan only evidence-supported questions.')
    assert 'at most 20 physical slides' in policy
    assert 'at most 5 physical slides' in policy
    assert 'counted separately' in policy
    assert 'analytical continuation is ALWAYS body content' in policy
    assert 'cannot increase the fixed body or introduction caps' in policy
    assert 'Plan only evidence-supported questions.' in policy


def test_retry_cannot_reuse_a_checkpoint_with_different_explicit_limits(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    from adaptive_document_agent.models.customization import PresentationBudget
    from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget
    from adaptive_document_agent.utils.hashing import sha256_bytes
    from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
    from tests.test_analysis_reliability_v126 import source_result
    source = b'checkpoint'
    result = source_result()
    result.document.sha256 = sha256_bytes(source)
    result.pipeline_state, result.retry_from, result.pipeline_version = 'partial', 'reporting', PIPELINE_VERSION
    result.profile.report_requirements = apply_presentation_budget(None, '',
        PresentationBudget(body_slides=20, introduction_slides=5))
    runner = DocumentOrchestrator(SimpleNamespace(cache=None))
    monkeypatch.setattr(runner, '_load_document', lambda *args: result.document)
    with pytest.raises(ValueError, match='budget differs'):
        runner.analyse_pdf(source, resume=result,
            presentation_budget=PresentationBudget(body_slides=18, introduction_slides=5))
