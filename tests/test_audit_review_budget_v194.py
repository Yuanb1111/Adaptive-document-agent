"""Regression for format repair exhausting content correction before its first draft."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _review_batch,
)
from tests.test_audit_review_contract_v174 import ScriptedGateway, unknown_draft, unknown_review
from tests.test_report_audit_scope_v174 import covered_source, fixture


def correction_case():
    result, binding = fixture()
    rejected = AuditScopeReview(verdicts=[], unresolved_accepted=False,
        unresolved_reason='amount has an exact covered Revenue row on page 5; its summary on '
        'page 1 need not be covered. The ratio must remain unknown.')
    corrected = AuditScopeDraft(bindings=[binding], unresolved_observation_ids=['ratio'],
        unresolved_reason='No assurance can be transferred to the derived ratio.')
    accepted = AuditScopeReview(verdicts=[dict(observation_id='amount', accepted=True,
        reason='Independently checked the exact row, column, unit and scope.',
        covered_source=covered_source(binding))], unresolved_accepted=True,
        unresolved_reason='The ratio has no independent assurance evidence.')
    return result, rejected, corrected, accepted


def test_format_then_rejection_delivers_full_feedback_to_writer_and_requires_fresh_review():
    result, rejected, corrected, accepted = correction_case()
    context = _context(result)
    original = deepcopy(context)
    gateway = ScriptedGateway([unknown_draft(), unknown_review(extra=True), rejected, corrected, accepted])
    record = dict(attempts=[])
    _review_batch(gateway, context, record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft, AuditScopeReview,
        AuditScopeReview, AuditScopeDraft, AuditScopeReview]
    assert len(record['attempts']) == 2 and record['status'] == 'complete'
    assert record['corrections_used'] == dict(binding_validation=0, independent_review=1, review_output=1)
    messages = gateway.calls[3][0]
    feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert feedback['independent_review'] == rejected.model_dump()
    assert feedback['validation_or_review_error'] == rejected.unresolved_reason
    assert feedback['corrective_kind'] == 'independent_review'
    assert all(call[0][1] == gateway.calls[0][0][1] for call in gateway.calls)
    assert record['draft'] == corrected.model_dump()
    assert record['review'] == accepted.model_dump()
    assert context == original


def test_format_repair_never_certifies_repeated_unknown_rejection():
    result, rejected, _, _ = correction_case()
    gateway = ScriptedGateway([unknown_draft(), unknown_review(extra=True), rejected,
        unknown_draft(), rejected])
    record = dict(attempts=[])
    with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
        _review_batch(gateway, _context(result), record)
    assert len(gateway.calls) == 5 and len(record['attempts']) == 2
    assert 'status' not in record
    assert record['corrections_used'] == dict(binding_validation=0, independent_review=1, review_output=1)


def test_reviewer_output_allowance_is_per_batch_not_reset_for_new_draft():
    result, rejected, corrected, _ = correction_case()
    gateway = ScriptedGateway([unknown_draft(), unknown_review(extra=True), rejected,
        corrected, unknown_review(extra=True)])
    record = dict(attempts=[])
    with pytest.raises(ValueError, match='review_output correction budget exhausted'):
        _review_batch(gateway, _context(result), record)
    assert len(gateway.calls) == 5 and len(record['attempts']) == 2
    assert record['attempts'][-1]['corrective_kind'] == 'review_output'
    assert 'status' not in record


def test_content_correction_still_runs_value_checks_and_needs_independent_proof():
    result, rejected, corrected, accepted = correction_case()
    invalid = corrected.model_copy(deep=True)
    invalid.bindings[0].source_raw_value = '120,463'
    gateway = ScriptedGateway([unknown_draft(), unknown_review(extra=True), rejected,
        invalid, corrected, accepted])
    record = dict(attempts=[])
    _review_batch(gateway, _context(result), record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft, AuditScopeReview,
        AuditScopeReview, AuditScopeDraft, AuditScopeDraft, AuditScopeReview]
    assert len(record['attempts']) == 3
    assert record['corrections_used'] == dict(binding_validation=1, independent_review=1, review_output=1)
    assert any('source_raw_value' in issue['field'] for issue in record['attempts'][1]['validation_issues'])
    assert record['status'] == 'complete'


def test_diagnostic_replay_stops_at_fresh_writer_without_fabricating_approval():
    from scripts.replay_audit_scope import replay_review_correction
    result, rejected, _, _ = correction_case()
    attempt = dict(draft=unknown_draft().model_dump(), review=rejected.model_dump(),
        review_contract_corrections=[dict(review=unknown_review(extra=True).model_dump())])
    replayed = replay_review_correction(_context(result), attempt)
    assert replayed['status'] == 'reached_writer_correction'
    assert replayed['operations'] == ['AuditScopeDraft', 'AuditScopeReview', 'AuditScopeReview', 'AuditScopeDraft']
    assert replayed['full_feedback_delivered'] is True
    assert replayed['semantic_approval'] is False
