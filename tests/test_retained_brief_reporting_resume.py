"""A rejected brief can reuse its bound plan without inheriting a final verdict."""
import json

import pytest

from adaptive_document_agent.agent.brief_reporting_resume import retained_brief_reporting
from adaptive_document_agent.agent.retained_analysis import selected_record
from adaptive_document_agent.agent.retained_analysis_review import review_complete, review_context
from adaptive_document_agent.models import PipelineResult, ValidationIssue
from adaptive_document_agent.models.presentation import CompanySummaryItem, CompanySummaryPage
from adaptive_document_agent.services.pipeline_completion import require_topic_coverage
from tests.test_retained_analysis_v216 import prepared


def checkpoint():
    result, gateway = prepared()
    result.pipeline_state, result.retry_from, result.failed_stage = 'partial', 'reporting', 'executive_brief'
    result.failure_details = {'component': 'ExecutiveBrief', 'message': 'Brief requires repair.'}
    result.report_markdown = 'Unbound Markdown must be regenerated.'
    result.document.pages[0].text = 'Summary\n' + result.document.pages[0].text
    result.presentation_plan.company.name = ''
    result.presentation_plan.company.summary_overview = CompanySummaryPage(title='Revenue', source_section='Summary',
        items=[CompanySummaryItem(label='Revenue', text='Revenue is reported.', source_pages=[234],
                                  source_quote='Revenue RMB thousands')])
    result.validation_warnings.append(ValidationIssue(code='executive_brief_failed', stage='report',
                                                     message='Prior failure', severity='warning'))
    current = PipelineResult(document=result.document.model_copy(deep=True), profile=result.profile.model_copy(deep=True),
        observations=[o.model_copy(deep=True) for o in result.observations],
        analysis_plan=result.analysis_plan, analysis_results=result.analysis_results)
    return result, current, gateway


def test_restore_validated_selection_and_plan_only_and_regenerate_markdown():
    source, current, gateway = checkpoint()
    selected_ids = selected_record(source)['selection']['ordered_insight_ids']
    source.validation_warnings.append(ValidationIssue(
        code='retained_selection_coverage', stage='presentation', message=json.dumps(dict(
            selected_ids=selected_ids, copy_review_ids=selected_ids,
            review=dict(missing_insight_ids=['omitted'], page_issues=[], reason='Check this omission at publication.')))))
    count = len(gateway.client.calls)
    reporting = retained_brief_reporting(source, current, gateway)
    assert reporting is not None
    assert reporting.presentation_plan == source.presentation_plan
    assert reporting.report_plan == source.report_plan and reporting.charts == source.charts
    assert reporting.report_markdown and reporting.report_markdown != source.report_markdown
    assert not reporting.executive_brief and not review_complete(reporting)
    assert review_context(reporting)['deferred_copy_review_objections'][0]['missing_insight_ids'] == ['omitted']
    with pytest.raises(ValueError, match='Retained-analysis evidence'):
        require_topic_coverage(reporting)
    assert len(gateway.client.calls) == count
    assert not any(w.code == 'executive_brief_failed' for w in reporting.validation_warnings)
    reporting.presentation_plan.title = 'Independent copy'
    assert source.presentation_plan.title != reporting.presentation_plan.title


@pytest.mark.parametrize('omissions_accepted', [True, False])
def test_final_source_retry_preserves_draft_but_never_inherits_rejected_review(omissions_accepted):
    import json
    source, current, gateway = checkpoint()
    source.failed_stage = 'presentation_coverage'
    source.failure_details = dict(component='PresentationCoverage', message='Chart display units differ')
    ids = [s.id for s in source.presentation_plan.slides if s.slide_type == 'analysis']
    source.validation_warnings.append(ValidationIssue(code='presentation_retained_analysis_review',
        stage='presentation', message=json.dumps(dict(contract=1, fingerprint='old-renderer-context',
            review=dict(verdicts=[dict(slide_id=sid,accepted=False,reason='Chart units differ') for sid in ids],
                        omissions_accepted=omissions_accepted, omission_reason='Selection reviewed')))))
    reporting = retained_brief_reporting(source, current, gateway)
    if not omissions_accepted:
        assert reporting is None
    else:
        assert reporting is not None and reporting.presentation_plan == source.presentation_plan
        assert not review_complete(reporting)
        assert not any(w.code == 'presentation_retained_analysis_review' for w in reporting.validation_warnings)
        with pytest.raises(ValueError, match='Retained-analysis evidence'):
            require_topic_coverage(reporting)


@pytest.mark.parametrize('change', ['source', 'audit', 'observation', 'calculation', 'focus', 'budget',
                                    'selection', 'plan', 'introduction', 'strategy', 'stage'])
def test_stale_or_inapplicable_upstream_work_falls_back_to_normal_planning(change):
    source, current, gateway = checkpoint()
    if change == 'source':
        current.document.pages[0].text += ' Additional source statement.'
    elif change == 'audit':
        current.profile.data_quality_notes.append('Additional source limitation.')
    elif change == 'observation':
        current.observations[0].raw_value = 'Changed source amount'
    elif change == 'calculation':
        current.analysis_results = []
    elif change == 'focus':
        assert retained_brief_reporting(source, current, gateway, requested_focus='A different question') is None
        return
    elif change == 'budget':
        from adaptive_document_agent.models.customization import ReportRequirements
        current.profile.report_requirements = ReportRequirements(original_request='At most two pages')
    elif change == 'selection':
        source.report_plan.title += ' Changed'
    elif change == 'plan':
        next(s for s in source.presentation_plan.slides if s.slide_type == 'analysis').insight_ids = []
    elif change == 'introduction':
        source.presentation_plan.company.summary_overview.items[0].source_quote = 'Not in the source'
    elif change == 'strategy':
        gateway.settings.presentation_strategy = 'full_catalog'
    else:
        source.failed_stage = 'presentation_coverage'
    assert retained_brief_reporting(source, current, gateway) is None


def test_normal_reporting_retry_reaches_current_brief_gates_with_prior_questions(monkeypatch):
    from hashlib import sha256
    import json
    from adaptive_document_agent.agent import prepared_executive_brief
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    from adaptive_document_agent.agent.retained_analysis import select_retained_analysis, selected_record
    from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget, fixed_presentation_budget
    from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
    from tests.test_retained_analysis_v216 import gateway as mock_gateway, selection
    source, _, _ = checkpoint()
    raw = b'Synthetic saved PDF used with the in-memory parser'
    source.document.sha256 = sha256(raw).hexdigest()
    source.pipeline_version = PIPELINE_VERSION
    source.profile.report_requirements = apply_presentation_budget(None, '', fixed_presentation_budget())
    gw = mock_gateway([selection(source)])
    select_retained_analysis(gw, source)
    original_selection = selected_record(source)
    source.validation_warnings.append(ValidationIssue(code='executive_brief_review_checkpoint', stage='report',
        message=json.dumps({'context_key':'old-check', 'checked':{'0':['Source scope missing']}})))
    source.validation_warnings.append(ValidationIssue(code='executive_brief_repair_audit', stage='report',
        message=json.dumps({'original':{'items':[{'label':'Finding', 'text':'Prior draft'}]},
                            'initial_errors':{'item_0':['Meaning review: Source scope missing']}})))
    runner = DocumentOrchestrator(gw)
    monkeypatch.setattr(runner, '_load_document', lambda *_: source.document.model_copy(deep=True))
    monkeypatch.setattr(runner, '_generate_report', lambda *_a, **_k: pytest.fail('Reran upstream selection'))
    visited = []
    def reject(gateway, snapshot, prepared):
        visited.append({w.code for w in snapshot.validation_warnings})
        raise ValueError('Independent reviewer still rejects this finding.')
    monkeypatch.setattr(prepared_executive_brief, 'current_executive_brief', reject)
    result = runner.analyse_pdf(raw, resume=source)
    assert visited and {'executive_brief_retry_feedback', 'executive_brief_review_checkpoint'} <= visited[0]
    assert result.pipeline_state == 'partial' and result.failed_stage == 'executive_brief'
    assert 'Independent reviewer still rejects' in result.failure_details['message']
    assert selected_record(result) == original_selection


def approve_preintegration_input(source):
    from adaptive_document_agent.agent.brief_review_checkpoint import context_key, save_checks
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    source.failed_stage = 'source_integration'
    source.failure_details = {'component': 'SourceIntegration', 'message': 'Integration protocol failed'}
    brief = ExecutiveBrief.model_validate(dict(title='Key findings', items=[dict(label='Revenue',
        text='Revenue is reported.', evidence=[dict(page=234, text='Revenue RMB thousands')])]))
    source.executive_brief = brief
    context = {'selected_analysis_topics': [], 'output_limits': {'maximum_findings': 5}}
    save_checks(source, context_key(brief, context, source), brief, {0: []}, {}, context)


@pytest.mark.parametrize('mutation', [None, 'body', 'evidence', 'context', 'environment', 'error',
                                      'pending', 'unavailable', 'missing_index', 'later_rejected'])
def test_integration_retry_requires_latest_exact_candidate_complete_approval_and_source(mutation):
    import json
    from adaptive_document_agent.agent.brief_reporting_resume import checked_integration_input
    source, current, gateway = checkpoint()
    approve_preintegration_input(source)
    last = source.validation_warnings[-1]
    record = json.loads(last.message)
    if mutation == 'body':
        source.executive_brief.items[0].text += ' Another claim.'
    elif mutation == 'evidence':
        source.executive_brief.items[0].evidence[0].text = 'A different quotation.'
    elif mutation == 'context':
        record['source_context']['selected_analysis_topics'] = [{'title':'Different topic','pages':[1]}]
    elif mutation == 'environment':
        record['environment_key'] = 'obsolete environment'
    elif mutation == 'error':
        record['checked']['0'] = ['Missing qualification.']
    elif mutation == 'pending':
        record['pending'] = [0]
    elif mutation == 'unavailable':
        record['unavailable'] = {'0':'Incomplete review'}
    elif mutation == 'missing_index':
        record['checked'] = {}
    elif mutation == 'later_rejected':
        last = last.model_copy(deep=True)
        source.validation_warnings.append(last)
        record['semantic_approval'] = False
    last.message = json.dumps(record)
    reporting = retained_brief_reporting(source, current, gateway)
    assert reporting is not None
    if mutation is None:
        assert reporting.executive_brief == source.executive_brief
        assert reporting.executive_brief is not source.executive_brief
        reporting.executive_brief.items[0].text += ' A later edit.'
        assert checked_integration_input(source, reporting) is None
        reporting.executive_brief = source.executive_brief.model_copy(deep=True)
        reporting.profile.analysis_focus = 'New evidence priorities after native budget preparation'
        assert checked_integration_input(source, reporting) is None
    else:
        assert reporting.executive_brief is None


def test_reused_accepted_brief_still_enters_normal_source_integration(monkeypatch):
    from hashlib import sha256
    from adaptive_document_agent.agent import prepared_executive_brief, source_integration_review
    from adaptive_document_agent.agent.orchestrator import DocumentOrchestrator
    from adaptive_document_agent.agent.retained_analysis import select_retained_analysis
    from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget, fixed_presentation_budget
    from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
    from tests.test_retained_analysis_v216 import gateway as mock_gateway, selection
    source, _, _ = checkpoint()
    raw = b'Synthetic input for exact source integration retry'
    source.document.sha256 = sha256(raw).hexdigest()
    source.pipeline_version = PIPELINE_VERSION
    source.profile.report_requirements = apply_presentation_budget(None, '', fixed_presentation_budget())
    gw = mock_gateway([selection(source)])
    select_retained_analysis(gw, source)
    approve_preintegration_input(source)
    runner = DocumentOrchestrator(gw)
    monkeypatch.setattr(runner, '_load_document', lambda *_: source.document.model_copy(deep=True))
    monkeypatch.setattr(prepared_executive_brief, 'current_executive_brief',
                        lambda *_a, **_k: pytest.fail('Unexpected independent briefing regeneration'))
    def reject(gateway, current, brief, **kwargs):
        assert brief == source.executive_brief
        raise ValueError('Fresh integration review rejected the response.')
    monkeypatch.setattr(source_integration_review, 'review_supplementary_sources', reject)
    result = runner.analyse_pdf(raw, resume=source)
    assert result.pipeline_state == 'partial' and result.failed_stage == 'source_integration'
    assert 'Fresh integration review rejected' in result.failure_details['message']
