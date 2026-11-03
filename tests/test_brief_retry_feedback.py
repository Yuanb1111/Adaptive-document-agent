"""An explicit reporting retry keeps failed questions, never prior approval."""
import json
import pytest

from adaptive_document_agent.agent.brief_retry_feedback import retain_feedback, current_feedback
from adaptive_document_agent.models import ValidationIssue
from tests.test_brief_semantic_repair import result_for, payload


def sample():
    result = result_for(['Revenue was USD 12 million.'])
    result.pipeline_state, result.failed_stage = 'partial', 'executive_brief'
    result.failure_details = {'message': 'The adjusted measure needs its source limitations.'}
    result.validation_warnings.append(ValidationIssue(code='executive_brief_repair_audit',
        stage='report', message=json.dumps(dict(original=payload('Revenue was USD 12 million.'),
            repair_errors=['Retain the non-comparability condition.'],
            post_source_meaning_correction={'errors': {'0': ['Cite the companion outcome.']}}))))
    return result


def test_reporting_retry_retains_untrusted_audience_and_failed_questions():
    previous = sample()
    previous.validation_warnings.append(ValidationIssue(code='executive_brief_review_checkpoint',
        stage='report', message=json.dumps({'checked': {'0': [], '1': ['Missing the item quotation.']}})))
    issue = retain_feedback(previous)
    current = previous.model_copy(deep=True)
    current.validation_warnings = [issue]
    feedback = current_feedback(current)
    assert feedback['issues'] == ['Retain the non-comparability condition.']
    assert feedback['context_questions'] == {'0': ['Cite the companion outcome.']}
    assert feedback['salvage_questions'] == {'1': ['Missing the item quotation.']}
    assert feedback['failure'] == previous.failure_details['message']
    assert set(feedback['rejected_audience'][0]) == {'label', 'text'}
    current.document.sha256 = 'different-document'
    assert current_feedback(current) is None


@pytest.mark.parametrize('change', ['stage', 'invalid_audit'])
def test_unrelated_or_invalid_failures_do_not_become_editorial_feedback(change):
    result = sample()
    if change == 'stage':
        result.failed_stage = 'presentation_planning'
    else:
        result.validation_warnings[-1].message = 'older plain-text diagnostic'
    assert retain_feedback(result) is None
