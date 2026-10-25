"""Changed physical selections must establish assurance before writing their brief."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent import presentation_budget_refinement as budget
from adaptive_document_agent.agent import report_audit_scope as audit
from adaptive_document_agent.models import DocumentPage
from adaptive_document_agent.models.coverage import SourceCheck, SourceCoverage
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.llm.exceptions import LLMConfigurationError, PrivacyViolationError
from tests.test_executive_brief import payload
from tests.test_physical_budget_refinement_v130 import measurement, source
from tests.test_report_audit_scope_v174 import fixture, Gateway


def _source():
    result, _, _, draft = source()
    for observation in result.observations:
        for evidence in observation.evidence:
            evidence.page = 1
    text = '\n'.join(o.evidence[0].text for o in result.observations)
    result.document.page_count = 1
    result.document.pages = [DocumentPage(page_number=1, text=text)]
    result.profile.analysis_page_ranges = [(1, 1)]
    result.profile.source_coverage = SourceCoverage(checks=[SourceCheck(
        section_id='source', pages=[1], status='checked_not_found',
        reason='Read the complete operational source.',
        decision_impact='Qualifies the reported measures.',
        finding='The source lists operational quantities without an assurance statement.')])
    from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
    result.presentation_plan = compile_topic_plan(result)
    draft.topics[0].caveats = ['Audit status is not established for these reported measures.']
    result.executive_brief = ExecutiveBrief.model_validate(payload('Previously reviewed operational performance.'))
    assert not audit.needs_report_audit_scope(result)
    return result, draft


def _payloads(messages):
    return [json.loads(message['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            for message in messages if message['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>')]


class BudgetAuditGateway:
    """Explicit synthetic independent unknown verdicts; real audit validators run."""
    def __init__(self, draft, *, accepted=True):
        self.draft = draft
        self.accepted = accepted
        self.calls = []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema is budget.PhysicalBudgetSelection:
            return self.draft.model_copy(deep=True)
        if schema is budget.PhysicalBudgetReview:
            return schema(accepted=True, reason='The selected recent reversal and adverse output remain.')
        if schema is audit.AuditScopeDraft:
            context = next(value for value in _payloads(messages)
                           if isinstance(value, dict) and 'observations' in value)
            return schema(unresolved_observation_ids=[o['id'] for o in context['observations']],
                          unresolved_reason='The complete source lists quantities without assurance evidence.')
        assert schema is audit.AuditScopeReview
        return schema(verdicts=[], unresolved_accepted=self.accepted,
                      unresolved_reason=('All supplied operational quantities lack assurance evidence.'
                                         if self.accepted else 'The proposed unknown disposition was independently rejected.'))


def _measure_selection(monkeypatch):
    def measured(result):
        oversized = len(result.presentation_topics.topics) == 3
        return measurement(result, 23 if oversized else 18, 12 if oversized else 8)
    monkeypatch.setattr(budget, 'measure', measured)


def test_budget_introduced_audit_scope_is_independently_reviewed_before_final_brief(monkeypatch):
    result, draft = _source()
    original_data = deepcopy((result.observations, result.document, result.analysis_results))
    gateway = BudgetAuditGateway(draft)
    _measure_selection(monkeypatch)
    from adaptive_document_agent.agent import executive_brief
    seen = []

    def write(self, current):
        audit.require_report_audit_scope(current)
        assert current.executive_brief is None
        seen.append(list(gateway.calls))
        return ExecutiveBrief.model_validate(payload('The final operational scope has been reviewed.'))

    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', write)
    assert budget.refine_presentation_budget(gateway, result)
    assert len(seen) == 1
    assert seen[0] == ['PhysicalBudgetSelection', 'PhysicalBudgetReview', 'AuditScopeDraft', 'AuditScopeReview']
    audit.require_report_audit_scope(result)
    assert result.executive_brief.items[0].text == 'The final operational scope has been reviewed.'
    assert any(w.code == 'report_audit_scope_review' for w in result.validation_warnings)
    assert (result.observations, result.document, result.analysis_results) == original_data


def test_rejected_candidate_audit_stops_brief_and_never_requests_another_omission(monkeypatch):
    result, draft = _source()
    original_data = deepcopy((result.observations, result.document, result.analysis_results))
    gateway = BudgetAuditGateway(draft, accepted=False)
    _measure_selection(monkeypatch)
    from adaptive_document_agent.agent import executive_brief

    def unexpected(*args):
        raise AssertionError('Rejected assurance must stop before briefing.')

    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', unexpected)
    with pytest.raises(budget.FinalBudgetAuditError, match='independently rejected') as failed:
        budget.refine_presentation_budget(gateway, result)
    assert isinstance(failed.value.failure, ValueError)
    assert gateway.calls.count('PhysicalBudgetSelection') == 1
    assert gateway.calls.count('PhysicalBudgetReview') == 1
    assert gateway.calls.count('AuditScopeDraft') == 2
    assert gateway.calls.count('AuditScopeReview') == 2
    diagnostics = [json.loads(w.message) for w in result.validation_warnings
                   if w.code == 'report_audit_scope_unresolved']
    assert diagnostics and 'independently rejected' in diagnostics[-1]['error']
    assert diagnostics[-1]['batches']
    assert not any(w.code == 'report_audit_scope_review' for w in result.validation_warnings)
    assert result.pipeline_state == 'partial' and result.retry_from == 'reporting'
    assert (result.observations, result.document, result.analysis_results) == original_data


def test_native_fitting_plan_new_scope_reviews_and_invalidates_earlier_brief(monkeypatch):
    result, draft = _source()
    gateway = BudgetAuditGateway(draft)
    measured_briefs = []

    def measured(current):
        current.presentation_plan.themes[1].caveats = list(draft.topics[0].caveats)
        measured_briefs.append(current.executive_brief)
        return measurement(current, 18, 8)

    monkeypatch.setattr(budget, 'measure', measured)
    from adaptive_document_agent.agent import executive_brief
    new_brief = ExecutiveBrief.model_validate(payload('The fitting final scope has been reviewed.'))

    def write(self, current):
        audit.require_report_audit_scope(current)
        assert current.executive_brief is None
        return new_brief

    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', write)
    assert not budget.refine_presentation_budget(gateway, result)
    assert gateway.calls == ['AuditScopeDraft', 'AuditScopeReview']
    assert result.executive_brief is new_brief
    assert len(measured_briefs) == 2 and measured_briefs[-1] is new_brief
    audit.require_report_audit_scope(result)


@pytest.mark.parametrize('reduced', [False, True])
def test_unchanged_or_reduced_approved_scope_reuses_review_and_preserves_brief(reduced):
    result, binding = fixture()
    result.observations[1].row_id = 1  # A distinct row makes a reduced target set observable.
    gateway = Gateway(binding)
    result.executive_brief = ExecutiveBrief.model_validate(payload('The initial brief predates assurance review.'))
    assert audit.refresh_report_audit_scope(gateway, result)
    assert result.executive_brief is None
    current_brief = ExecutiveBrief.model_validate(payload('The current brief follows assurance review.'))
    result.executive_brief = current_brief
    if reduced:
        result.presentation_plan.themes[0].observation_ids = ['amount']
    assert not audit.refresh_report_audit_scope(gateway, result)
    assert result.executive_brief is current_brief
    assert len(gateway.calls) == 2
    audit.require_report_audit_scope(result)


def test_changed_source_expires_review_and_the_brief_after_fresh_acceptance():
    result, binding = fixture()
    gateway = Gateway(binding)
    audit.refresh_report_audit_scope(gateway, result)
    result.executive_brief = ExecutiveBrief.model_validate(payload('The current brief follows assurance review.'))
    result.document.pages[-1].text += ' Additional source note.'
    assert audit.refresh_report_audit_scope(gateway, result)
    assert result.executive_brief is None
    assert len(gateway.calls) == 4
    audit.require_report_audit_scope(result)


@pytest.mark.parametrize('error_type', [LLMConfigurationError, PrivacyViolationError])
def test_terminal_gateway_failure_retains_candidate_audit_and_original_exception(monkeypatch, error_type):
    result, draft = _source()
    failure = error_type('The configured audit route cannot run.')

    class FailingGateway(BudgetAuditGateway):
        def generate_structured(self, messages, schema, **kwargs):
            if schema is audit.AuditScopeDraft:
                raise failure
            return super().generate_structured(messages, schema, **kwargs)

    gateway = FailingGateway(draft)
    _measure_selection(monkeypatch)
    from adaptive_document_agent.agent import executive_brief

    def unexpected(*args):
        raise AssertionError('A failed audit route cannot continue to briefing.')

    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', unexpected)
    with pytest.raises(error_type) as failed:
        budget.refine_presentation_budget(gateway, result)
    assert failed.value is failure
    assert gateway.calls.count('PhysicalBudgetSelection') == 1
    diagnostic = next(json.loads(w.message) for w in result.validation_warnings
                      if w.code == 'report_audit_scope_unresolved')
    assert diagnostic['error'] == str(failure)
    assert diagnostic['context']['observations']


def test_audit_refreshed_fitting_brief_uses_new_geometry_for_budget_selection(monkeypatch):
    result, draft = _source()
    gateway = BudgetAuditGateway(draft)
    costs = iter([18, 23, 18, 18])
    measured = []

    def measure(current):
        if len(current.presentation_topics.topics) == 3:
            current.presentation_plan.themes[1].caveats = list(draft.topics[0].caveats)
        total = next(costs)
        measured.append(total)
        return measurement(current, total, 12 if total == 23 else 8)

    monkeypatch.setattr(budget, 'measure', measure)
    from adaptive_document_agent.agent import executive_brief
    briefs = []

    def write(self, current):
        audit.require_report_audit_scope(current)
        briefs.append(current.presentation_topics.model_dump())
        return ExecutiveBrief.model_validate(payload('Reviewed source qualifications remain visible.'))

    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', write)
    assert budget.refine_presentation_budget(gateway, result)
    assert measured == [18, 23, 18, 18]
    assert len(briefs) == 2
    assert gateway.calls == ['AuditScopeDraft', 'AuditScopeReview',
                             'PhysicalBudgetSelection', 'PhysicalBudgetReview']
    audit.require_report_audit_scope(result)


def test_accepted_candidate_audit_survives_a_later_brief_failure_and_can_resume(monkeypatch):
    result, draft = _source()
    gateway = BudgetAuditGateway(draft)
    _measure_selection(monkeypatch)
    from adaptive_document_agent.agent import executive_brief
    captured = []

    def failed(self, current):
        audit.require_report_audit_scope(current)
        captured.append(current.model_copy(deep=True))
        raise ValueError('The final briefing has an unsupported source claim.')

    monkeypatch.setattr(executive_brief.ExecutiveBriefWriter, 'generate', failed)
    with pytest.raises(budget.FinalBudgetBriefError, match='unsupported source claim'):
        budget.refine_presentation_budget(gateway, result)
    saved = next(w for w in result.validation_warnings if w.code == 'report_audit_scope_review')
    assert gateway.calls.count('PhysicalBudgetSelection') == 1
    candidate = captured[0]
    candidate.validation_warnings = [saved]
    before = list(gateway.calls)
    assert not audit.refresh_report_audit_scope(gateway, candidate)
    assert gateway.calls == before
    audit.require_report_audit_scope(candidate)
