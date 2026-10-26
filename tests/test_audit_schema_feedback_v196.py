"""Batch rationale capacity and precise output feedback preserve evidence rejection."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.report_audit_scope import (
    AUDIT_BATCH_REASON_CHARS, AuditScopeDraft, AuditScopeReview, _context, _review_batch,
    review_report_audit_scope, reviewed_audit_bindings,
)
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_audit_review_contract_v174 import ScriptedGateway, unknown_draft, unknown_review
from tests.test_audit_review_budget_v194 import correction_case
from tests.test_budget_output_v145 import response
from tests.test_report_audit_scope_v174 import fixture, Gateway


@pytest.mark.parametrize('length', [1450, 1453, AUDIT_BATCH_REASON_CHARS])
def test_batch_reason_capacity_preserves_rejection_and_reaches_writer(length):
    result, rejected, corrected, accepted = correction_case()
    reason = rejected.unresolved_reason.ljust(length, '.')
    rejected = AuditScopeReview.model_validate({**rejected.model_dump(), 'unresolved_reason': reason})
    gateway = ScriptedGateway([unknown_draft(), rejected, corrected, accepted])
    record = dict(attempts=[])
    _review_batch(gateway, _context(result), record)
    assert len(gateway.calls) == 4
    assert record['corrections_used'] == dict(draft_output=0, binding_validation=0, independent_review=1, review_output=0)
    feedback = json.loads(gateway.calls[2][0][-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert feedback['independent_review']['unresolved_reason'] == reason
    assert feedback['independent_review']['unresolved_accepted'] is False
    assert record['status'] == 'complete'


def test_reason_cap_remains_bounded_for_both_batch_schemas():
    assert AUDIT_BATCH_REASON_CHARS == 4200
    for schema, value in [(AuditScopeDraft, unknown_draft()), (AuditScopeReview, unknown_review())]:
        with pytest.raises(ValidationError, match='4200'):
            schema.model_validate({**value.model_dump(), 'unresolved_reason': 'x' * 4201})


def test_overlong_complete_review_receives_exact_field_limit_before_content_correction():
    result, rejected, corrected, accepted = correction_case()
    raw = json.dumps({**rejected.model_dump(), 'unresolved_reason': 'x' * 4201})
    error = LLMStructuredOutputError('Bounded response failed schema validation', response=response(raw))
    gateway = ScriptedGateway([unknown_draft(), error, rejected, corrected, accepted])
    record = dict(attempts=[])
    _review_batch(gateway, _context(result), record)
    detail = record['attempts'][0]['review_contract_corrections'][0]
    assert detail['raw_response'] == raw
    assert detail['schema_errors'][0]['loc'] == ['unresolved_reason']
    assert detail['schema_errors'][0]['type'] == 'string_too_long'
    assert detail['schema_errors'][0]['ctx']['max_length'] == 4200
    assert 'input' not in detail['schema_errors'][0]
    retry_messages = gateway.calls[2][0]
    feedback = json.loads(retry_messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert feedback['schema_errors'] == detail['schema_errors']
    assert 'Rephrase overlong' in retry_messages[-1]['content']
    assert record['corrections_used'] == dict(draft_output=0, binding_validation=0, independent_review=1, review_output=1)


def test_repeated_overlong_output_still_stops_with_full_diagnostics():
    result, _ = fixture()
    raw = json.dumps({**unknown_review().model_dump(), 'unresolved_reason': 'x' * 4201})
    error = LLMStructuredOutputError('Bounded response failed schema validation', response=response(raw))
    gateway = ScriptedGateway([unknown_draft(), error, error])
    record = dict(attempts=[])
    with pytest.raises(ValueError, match='review_output correction budget exhausted') as failure:
        _review_batch(gateway, _context(result), record)
    assert 'unresolved_reason' in str(failure.value) and '4200' in str(failure.value)
    assert len(gateway.calls) == 3 and 'status' not in record
    assert all(failure['schema_errors'][0]['ctx']['max_length'] == 4200
        for failure in record['attempts'][0]['review_contract_corrections'])


@pytest.mark.parametrize('accepted', [True, False])
def test_category_row_binding_preserves_broad_metric_and_requires_independent_approval(accepted):
    result, binding = fixture()
    amount = result.observations[0]
    amount.metric_original = amount.metric_canonical = 'Income'
    amount.parent_section = 'Income'
    amount.dimensions['category'] = 'Revenue'
    amount.category_dimensions['category'] = 'Revenue'
    original = deepcopy((result.observations, result.document))
    gateway = Gateway(binding, accepted=accepted)
    if accepted:
        review_report_audit_scope(gateway, result)
        assert set(reviewed_audit_bindings(result)) == {'amount'}
    else:
        with pytest.raises(ValueError, match='Wrong scope'):
            review_report_audit_scope(gateway, result)
        assert not reviewed_audit_bindings(result)
    assert (result.observations, result.document) == original
    for _, messages, _ in gateway.calls:
        assert 'category_dimensions' in messages[0]['content']
        assert 'Never rename retained observations' in messages[0]['content']
