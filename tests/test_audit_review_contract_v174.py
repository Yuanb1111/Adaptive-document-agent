"""Reviewer output repair cannot consume or replace a writer's evidence correction."""
from concurrent.futures import CancelledError
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.report_audit_batches import AuditReviewContractError, validate_review
from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _review_batch,
)
from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from tests.test_budget_output_v145 import response
from tests.test_report_audit_scope_v174 import covered_source, fixture


def unknown_draft():
    return AuditScopeDraft(unresolved_observation_ids=['amount', 'ratio'],
        unresolved_reason='No precise table scope has been established for these two measures.')


def unknown_review(*, extra=False, accepted=True):
    return AuditScopeReview(verdicts=[dict(observation_id=oid, accepted=False,
        reason='The proposed unknown status is supported.') for oid in ['amount', 'ratio']] if extra else [],
        unresolved_accepted=accepted, unresolved_reason='The exact table assurance remains unknown.')


class ScriptedGateway:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((deepcopy(messages), schema, kwargs))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        assert isinstance(output, schema)
        return output


def run(outputs):
    result, _ = fixture()
    context = _context(result)
    original = deepcopy(context)
    gateway, record = ScriptedGateway(outputs), dict(attempts=[])
    _review_batch(gateway, context, record)
    assert context == original
    return gateway, record


def test_all_unknown_extra_verdicts_are_rejected_then_reviewer_corrects_same_draft():
    draft, invalid, valid = unknown_draft(), unknown_review(extra=True), unknown_review()
    with pytest.raises(AuditReviewContractError, match='verdicts must be'):
        validate_review(draft, invalid)
    gateway, record = run([draft, invalid, valid])
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft, AuditScopeReview, AuditScopeReview]
    assert len(record['attempts']) == 1
    assert record['corrections_used'] == dict(binding_validation=0, independent_review=0, review_output=1)
    assert record['draft'] == draft.model_dump()
    assert record['review'] == valid.model_dump()
    entry = record['attempts'][0]
    assert entry['review_contract_corrections'][0]['review'] == invalid.model_dump()
    assert len(entry['review_output_attempts']) == 2
    assert gateway.calls[2][0][:3] == gateway.calls[1][0]
    assert 'verdicts=[]' in gateway.calls[1][0][0]['content']
    assert all('typographic table dot leaders' in call[0][0]['content'] for call in gateway.calls)


@pytest.mark.parametrize('kind', ['missing', 'extra', 'duplicate'])
def test_mixed_review_exact_binding_ledger_is_corrected_without_rewriting_sources(kind):
    _, binding = fixture()
    draft = AuditScopeDraft(bindings=[binding], unresolved_observation_ids=['ratio'],
        unresolved_reason='The ratio has no independent amount assurance.')
    accepted = dict(observation_id='amount', accepted=True, reason='Exact covered source.',
        covered_source=covered_source(binding))
    valid = AuditScopeReview(verdicts=[accepted], unresolved_accepted=True,
        unresolved_reason='The ratio is correctly unknown.')
    invalid = valid.model_copy(deep=True)
    invalid.verdicts = ([] if kind == 'missing' else
        valid.verdicts * 2 if kind == 'duplicate' else
        valid.verdicts + [valid.verdicts[0].model_copy(update=dict(observation_id='ratio', accepted=False))])
    gateway, record = run([draft, invalid, valid])
    assert len(gateway.calls) == 3 and record['status'] == 'complete'
    assert record['review']['verdicts'][0]['covered_source'] == covered_source(binding)


def test_repeated_review_format_failure_cannot_borrow_writer_correction():
    result, _ = fixture()
    gateway = ScriptedGateway([unknown_draft(), unknown_review(extra=True),
        unknown_review(extra=True)])
    record = dict(attempts=[])
    with pytest.raises(ValueError, match='review_output correction budget exhausted'):
        _review_batch(gateway, _context(result), record)
    assert len(gateway.calls) == 3 and len(record['attempts']) == 1
    assert record['corrections_used'] == dict(binding_validation=0, independent_review=0, review_output=1)
    assert 'status' not in record


def test_review_format_repair_remains_available_after_semantic_writer_correction():
    result, _ = fixture()
    draft = unknown_draft()
    gateway = ScriptedGateway([draft, unknown_review(accepted=False), draft,
        unknown_review(extra=True), unknown_review()])
    record = dict(attempts=[])
    _review_batch(gateway, _context(result), record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft, AuditScopeReview] * 2 + [AuditScopeReview]
    assert record['corrections_used']['independent_review'] == 1
    assert record['corrections_used']['review_output'] == 1
    assert record['status'] == 'complete'


def test_complete_review_format_error_uses_only_reviewer_output_correction():
    error = LLMStructuredOutputError('Invalid complete schema', response=response('{"wrong":true}', finish='stop'))
    gateway, record = run([unknown_draft(), error, unknown_review()])
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft, AuditScopeReview, AuditScopeReview]
    assert record['attempts'][0]['review_contract_corrections'][0]['raw_response'] == '{"wrong":true}'
    assert record['corrections_used'] == dict(binding_validation=0, independent_review=0, review_output=1)


@pytest.mark.parametrize('error', [LLMTransportError('Offline'), PrivacyViolationError('Local only'), CancelledError()])
def test_non_content_failures_never_consume_or_trigger_review_correction(error):
    result, _ = fixture()
    gateway, record = ScriptedGateway([unknown_draft(), error]), dict(attempts=[])
    with pytest.raises(type(error)):
        _review_batch(gateway, _context(result), record)
    assert len(gateway.calls) == 2
    assert record['corrections_used']['independent_review'] == 0
    assert not record['attempts'][0].get('review_contract_corrections')


def test_exhausted_review_length_keeps_capacity_diagnostics_and_never_uses_format_correction():
    result, _ = fixture()
    error = LLMStructuredOutputError('Truncated', response=response('{"verdicts":', finish='length'))
    gateway, record = ScriptedGateway([unknown_draft(), error, error]), dict(attempts=[])
    with pytest.raises(LLMStructuredOutputError):
        _review_batch(gateway, _context(result), record)
    assert [call[2]['max_tokens'] for call in gateway.calls] == [20000, 16384, 24000]
    assert gateway.calls[1][0] == gateway.calls[2][0]
    assert record['corrections_used']['independent_review'] == 0
    assert [a['status'] for a in record['attempts'][0]['review_output_attempts']] == ['truncated', 'truncated']
    assert not record['attempts'][0].get('review_contract_corrections')
