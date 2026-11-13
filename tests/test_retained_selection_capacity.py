"""A length-limited selection never becomes a parsed or approved draft."""
from copy import deepcopy
from concurrent.futures import CancelledError
import json
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.retained_analysis import SourceAuthoredAnalysisSelection
from adaptive_document_agent.agent.retained_selection_feedback import restore_rejected_findings
from adaptive_document_agent.agent.retained_selection_request import selection_request, SELECTION_TOKEN_LIMITS
from adaptive_document_agent.models import PipelineResult, ValidationIssue
from adaptive_document_agent.services.analysis_deadline import AnalysisTimeLimitExceeded
from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from tests.test_budget_output_v145 import gateway, response
from tests.test_retained_analysis_v216 import _linked_result, selection


def test_empty_reasoning_only_truncation_retries_complete_sources_at_larger_capacity():
    result = _linked_result()
    draft=selection(result)
    for decision in draft['decisions']:
        decision['page']=dict(title='Source measure',message='The source reports the measure.')
    value = SourceAuthoredAnalysisSelection.model_validate(draft)
    truncated = response('', finish='length')
    truncated.usage.output_tokens = truncated.usage.reasoning_tokens = SELECTION_TOKEN_LIMITS[0]
    llm, client = gateway([truncated, response(value)])
    messages = [dict(role='user', content='The complete untrusted source packet.')]
    before = deepcopy(messages), result.model_dump()
    actual = selection_request(llm, messages, type(value), result, 0,
        max_tokens=SELECTION_TOKEN_LIMITS[0], capacity_tokens=SELECTION_TOKEN_LIMITS[1])
    assert actual == value
    assert [kw['max_tokens'] for _, kw in client.requests] == list(SELECTION_TOKEN_LIMITS)
    assert client.requests[0][0] == client.requests[1][0]
    assert messages == before[0]
    assert result.model_dump(exclude={'validation_warnings'}) == {
        k: v for k, v in before[1].items() if k != 'validation_warnings'}
    audit = json.loads(result.validation_warnings[-1].message)
    assert [a['status'] for a in audit['attempts']] == ['truncated', 'response_received']
    assert audit['attempts'][0]['raw_response'] == ''
    assert audit['attempts'][0]['usage']['reasoning_tokens'] == SELECTION_TOKEN_LIMITS[0]
    assert not any(w.code in {'presentation_retained_analysis_selection',
        'presentation_retained_analysis_review'} for w in result.validation_warnings)


def test_two_truncations_stop_without_continuing_or_merging_partial_output():
    result = _linked_result()
    llm, client = gateway([response('{"decisions":[', finish='length')] * 2)
    with pytest.raises(LLMStructuredOutputError, match='truncated'):
        selection_request(llm, [dict(role='user', content='Complete sources.')],
            SourceAuthoredAnalysisSelection, result, 0)
    assert len(client.requests) == 2 and client.requests[0][0] == client.requests[1][0]
    assert not any(w.code == 'presentation_retained_analysis_selection' for w in result.validation_warnings)
    audit = json.loads(result.validation_warnings[-1].message)
    assert [a['capacity_retry'] for a in audit['attempts']] == [True, False]


@pytest.mark.parametrize('error', [LLMTransportError('Unavailable'), PrivacyViolationError('Local Only'),
                                  CancelledError(), AnalysisTimeLimitExceeded()])
def test_capacity_path_does_not_retry_transport_privacy_cancellation_or_deadline(error):
    class Stopped:
        calls = 0
        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            raise error
    llm = Stopped()
    with pytest.raises(type(error)) as caught:
        selection_request(llm, [], SourceAuthoredAnalysisSelection, _linked_result(), 0)
    assert caught.value is error and llm.calls == 1


def truncated_checkpoint():
    previous = _linked_result()
    # This fixture exercises checkpoint transport only, never a real verdict.
    previous.pipeline_state, previous.retry_from = 'partial', 'reporting'
    previous.failed_stage = 'presentation_selection'
    previous.failure_details = dict(component='RetainedAnalysisSelection', error_type='LLMStructuredOutputError')
    previous.validation_warnings.append(ValidationIssue(code='retained_selection_format_repair',
        stage='presentation', message=json.dumps(dict(status='truncated', raw_response=''))))
    assert previous.insights and previous.report_plan is not None
    return previous


def current_snapshot(previous):
    return PipelineResult(**{k: deepcopy(getattr(previous, k)) for k in
        ('document', 'profile', 'observations', 'analysis_plan', 'analysis_results')})


def test_truncated_selection_restores_only_source_identical_provisional_findings():
    previous = truncated_checkpoint()
    current = current_snapshot(previous)
    original = deepcopy(previous)
    assert restore_rejected_findings(previous, current)
    assert previous == original
    assert current.insights == previous.insights and current.report_plan == previous.report_plan
    assert current.presentation_plan is None
    assert [w.code for w in current.validation_warnings] == ['retained_selection_upstream_resume']
    current.insights[0].title = 'Changed local draft'
    assert current.insights != previous.insights


@pytest.mark.parametrize('changed', ['document', 'profile', 'observations', 'analysis_plan', 'analysis_results'])
def test_truncated_selection_cannot_reuse_findings_across_a_changed_snapshot(changed):
    previous = truncated_checkpoint()
    current = current_snapshot(previous)
    if changed == 'document':
        current.document.pages[0].text += ' Changed source.'
    elif changed == 'profile':
        current.profile.analysis_focus = 'A different user request'
    elif changed == 'observations':
        current.observations[0].raw_value = '999999'
    else:
        setattr(current, changed, [])
    assert not restore_rejected_findings(previous, current)
    assert not current.insights


@pytest.mark.parametrize('kind', ['invalid_format', 'wrong_stage', 'complete'])
def test_unproven_selection_failure_does_not_gain_upstream_resume(kind):
    previous = truncated_checkpoint()
    if kind == 'invalid_format':
        previous.validation_warnings[-1].message = json.dumps(dict(status='failed'))
    elif kind == 'wrong_stage':
        previous.failed_stage = 'executive_brief'
    else:
        previous.pipeline_state = 'complete'
    assert not restore_rejected_findings(previous, current_snapshot(previous))


@pytest.mark.parametrize('audit', [[], None, {'attempts': [None]}])
def test_malformed_capacity_diagnostics_fail_closed(audit):
    previous = truncated_checkpoint()
    previous.validation_warnings[-1].message = json.dumps(audit)
    assert not restore_rejected_findings(previous, current_snapshot(previous))


def test_private_813_truncation_reuses_findings_without_parsing_any_response():
    path = os.environ.get('ADA_SELECTION_813_DIAGNOSTIC')
    if not path:
        pytest.skip('Set ADA_SELECTION_813_DIAGNOSTIC for the private .813 checkpoint.')
    previous = PipelineResult.model_validate_json(Path(path).read_bytes())
    current = current_snapshot(previous)
    assert restore_rejected_findings(previous, current)
    assert current.insights == previous.insights
    assert current.observations == previous.observations
    assert current.presentation_plan is None
    assert not any(w.code == 'presentation_retained_analysis_selection' for w in current.validation_warnings)


def test_initial_copy_error_uses_local_repair_without_rewriting_accepted_siblings():
    from adaptive_document_agent.agent import retained_analysis as retained
    from tests.test_retained_source_citations import fixture
    from tests.test_retained_analysis_v216 import gateway as protocol_gateway
    result, _, proposal = fixture()
    bad_id = proposal.ordered_insight_ids[0]
    sibling = proposal.decisions[0].model_copy(deep=True, update={'insight_id': 'unchanged-sibling'})
    result.insights.append(result.insights[0].model_copy(deep=True, update={'id': sibling.insight_id}))
    proposal.decisions.append(sibling)
    proposal.ordered_insight_ids.append(sibling.insight_id)
    original_sibling = sibling.page.model_dump()
    proposal.decisions[0].page.message = 'Revenue was RMB987,654,321 in FY2025.'
    accepted = dict(accepted=True, reason='Synthetic copy-review protocol check.')
    llm = protocol_gateway([proposal.model_dump(), accepted,
        dict(edits={bad_id: dict(message=[dict(span_id='copy-0', after='The source reports revenue.')])}),
        accepted])
    retained.select_retained_analysis(llm, result)
    record = retained.selected_record(result)
    assert next(d['page'] for d in record['selection']['decisions']
                if d['insight_id'] == sibling.insight_id) == original_sibling
    assert [u['operation'] for u in llm.usage] == ['SourceAuthoredAnalysisSelection',
        'RetainedSelectionCoverage', 'RetainedPageRevisions', 'RetainedSelectionCoverage']
    assert not any(w.code == 'presentation_retained_analysis_review' for w in result.validation_warnings)
