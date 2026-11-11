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


def test_quantity_lock_rejection_requests_a_full_source_patch_without_granting_values():
    previous = sample()
    audit = json.loads(previous.validation_warnings[-1].message)
    audit['post_source_meaning_correction']['errors_after'] = [
        "item_0: meaning correction introduced new quantities: [('', '395', '')]"]
    previous.validation_warnings[-1].message = json.dumps(audit)
    feedback = json.loads(retain_feedback(previous).message)
    assert feedback['source_correction_required'] is True
    assert feedback['rejected_audience'][0]['text'] == 'Revenue was USD 12 million.'
    assert '395' not in str(feedback['rejected_audience'])


def test_retry_merges_all_failed_reviews_and_maps_selection_local_indices():
    previous = sample()
    audit = json.loads(previous.validation_warnings[-1].message)
    audit['salvage'] = dict(meaning_errors={'0': ['Narrow the absence qualifier.']},
        selection_meaning_errors={'3': ['Retain approximation.']},
        selection_context_correction=dict(original_indices=[2, 3, 4],
            post_source_meaning_correction=dict(
                meaning_errors_after={'0': ['Retain the subsequent outcome.'], '1': []},
                errors_after=['Retain the subsequent outcome.'])))
    previous.validation_warnings[-1].message = json.dumps(audit)
    feedback = json.loads(retain_feedback(previous).message)
    assert feedback['salvage_questions'] == {'0': ['Narrow the absence qualifier.'],
        '3': ['Retain approximation.'], '2': ['Retain the subsequent outcome.']}
    assert feedback['post_selection_questions'] == ['Retain the subsequent outcome.']
    assert 'approved' not in str(feedback)


def test_legacy_selection_verdict_is_kept_without_guessing_an_item():
    previous = sample()
    audit = json.loads(previous.validation_warnings[-1].message)
    audit['salvage'] = {'selection_context_correction': {
        'post_source_meaning_correction': {'errors_after': ['Retain later context.']}}}
    previous.validation_warnings[-1].message = json.dumps(audit)
    feedback = json.loads(retain_feedback(previous).message)
    assert feedback['salvage_questions'] == {}
    assert feedback['post_selection_questions'] == ['Retain later context.']


def test_source_invalid_item_does_not_resume_a_quantity_locked_text_patch():
    previous = sample()
    audit = json.loads(previous.validation_warnings[-1].message)
    audit['initial_errors'] = {'item_0': ['Unsupported numeric claim.']}
    previous.validation_warnings[-1].message = json.dumps(audit)
    assert json.loads(retain_feedback(previous).message)['source_correction_required'] is True


def test_reopened_locked_item_question_survives_final_whole_brief_review():
    previous = sample()
    audit = json.loads(previous.validation_warnings[-1].message)
    audit['post_source_meaning_correction']['meaning_errors_after'] = {
        '1': ['Retain the separate reconciliation basis.']}
    previous.validation_warnings[-1].message = json.dumps(audit)
    feedback = json.loads(retain_feedback(previous).message)
    assert feedback['context_questions'] == {'0': ['Cite the companion outcome.'],
        '1': ['Retain the separate reconciliation basis.']}


def test_budgeted_failure_feedback_is_bound_to_candidate_selection():
    from adaptive_document_agent.models import PresentationTopicSelection
    result = sample()
    topics = PresentationTopicSelection(topics=[])
    result.presentation_topics = None
    result.validation_warnings.append(ValidationIssue(code='presentation_budget_brief_failed',
        stage='report', message=json.dumps(dict(applied_selection=topics.model_dump(),
            brief_audits=[result.validation_warnings[-1].model_dump()]))))
    issue = retain_feedback(result)
    result.validation_warnings = [issue]
    assert current_feedback(result) is None
    result.presentation_topics = topics
    assert current_feedback(result)['issues'] == ['Retain the non-comparability condition.']


def test_budget_retry_uses_latest_nested_draft_lineage():
    from adaptive_document_agent.agent.brief_review_checkpoint import retry_checkpoints
    result = sample()
    def checkpoint(key):
        return ValidationIssue(code='executive_brief_review_checkpoint', stage='report',
            message=json.dumps({'context_key': key}))
    older, latest = checkpoint('before-budget'), checkpoint('within-budget')
    result.validation_warnings += [older, ValidationIssue(code='presentation_budget_brief_failed',
        stage='report', message=json.dumps({'brief_audits': [latest.model_dump()]}))]
    assert retry_checkpoints(result) == [latest]


@pytest.mark.parametrize('change', ['stage', 'invalid_audit'])
def test_unrelated_or_invalid_failures_do_not_become_editorial_feedback(change):
    result = sample()
    if change == 'stage':
        result.failed_stage = 'presentation_planning'
    else:
        result.validation_warnings[-1].message = 'older plain-text diagnostic'
    assert retain_feedback(result) is None
