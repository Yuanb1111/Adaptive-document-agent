"""Draft schema repair preserves the bounded source-binding correction opportunity."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _review_batch,
)
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_audit_binding_eligibility_v174 import percentage_case
from tests.test_audit_review_contract_v174 import ScriptedGateway
from tests.test_budget_output_v145 import response


def ratio_outputs():
    result, binding = percentage_case()
    invalid = AuditScopeDraft(bindings=[binding])
    raw = invalid.model_dump()
    raw['bindings'][0]['value_quote']['text'] = '3.1'
    raw = json.dumps(raw)
    malformed = LLMStructuredOutputError('Bounded response failed schema validation',
        response=response(raw))
    unknown = AuditScopeDraft(unresolved_observation_ids=['ratio'],
        unresolved_reason='The retained percentage has no supplied direct assurance chain; '
                          'the underlying amount assurance cannot establish the ratio status.')
    accepted = AuditScopeReview(verdicts=[], unresolved_accepted=True,
        unresolved_reason='The supplied percentage row has no exact assured counterpart.')
    rejected = accepted.model_copy(update={'unresolved_accepted': False,
        'unresolved_reason': 'The explanation omits relevant source evidence and is not accepted.'})
    return result, invalid, malformed, unknown, accepted, rejected


def contract_payloads(messages):
    """Find contract data without depending on its position in the prompt."""
    for message in messages:
        text = message['content']
        if '\n' not in text:
            continue
        try:
            payload = json.loads(text.split('\n', 1)[1].rsplit('\n', 1)[0])
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and 'target_contracts' in payload:
            yield payload


def assert_ratio_contract(messages):
    payloads = list(contract_payloads(messages))
    assert payloads, 'Eligibility must be supplied before a schema-valid draft exists.'
    contract = payloads[-1]['target_contracts'][0]
    assert contract['observation_id'] == 'ratio'
    assert contract['allowed_dispositions'] == ['unresolved']
    assert contract['retained_target']['unit'] == 'percent'
    assert contract['retained_target']['unit_family'] == 'percentage'
    assert contract['target_quote']['required_raw_value'] == '3.1'


@pytest.mark.parametrize('order', ['schema_then_binding', 'binding_then_schema'])
def test_draft_schema_and_binding_corrections_each_reach_independent_unknown_review(order):
    result, invalid, malformed, unknown, accepted, _ = ratio_outputs()
    failures = [malformed, invalid] if order == 'schema_then_binding' else [invalid, malformed]
    gateway = ScriptedGateway([*failures, unknown, accepted])
    context = _context(result)
    original = deepcopy((context, result.document, result.observations, result.analysis_results))
    record = dict(attempts=[])
    _review_batch(gateway, context, record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft] * 3 + [AuditScopeReview]
    assert record['correction_limits'] == dict(draft_output=1, binding_validation=1,
        independent_review=1, review_output=1, max_drafts=3)
    assert record['corrections_used'] == dict(draft_output=1, binding_validation=1,
        independent_review=0, review_output=0)
    assert record['status'] == 'complete'
    assert record['draft'] == unknown.model_dump(mode='json')
    assert record['review'] == accepted.model_dump(mode='json')
    assert (context, result.document, result.observations, result.analysis_results) == original
    assert_ratio_contract(gateway.calls[0][0])
    schema_index = 0 if order == 'schema_then_binding' else 1
    failure = record['attempts'][schema_index]
    assert failure['corrective_kind'] == 'draft_output'
    assert failure['format_failure']['raw_response'] == malformed.response.text
    issue = failure['format_failure']['schema_errors'][0]
    assert issue['loc'] == ['bindings', 0, 'value_quote', 'text']
    assert issue['ctx']['min_length'] == 8
    assert_ratio_contract(gateway.calls[schema_index + 1][0])


def test_repeated_draft_schema_error_cannot_borrow_binding_or_review_corrections():
    result, _, malformed, _, _, _ = ratio_outputs()
    gateway = ScriptedGateway([malformed, malformed])
    context, record = _context(result), dict(attempts=[])
    original = deepcopy(context)
    with pytest.raises(ValueError, match='draft_output correction budget exhausted'):
        _review_batch(gateway, context, record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft] * 2
    assert record['corrections_used'] == dict(draft_output=1, binding_validation=0,
        independent_review=0, review_output=0)
    assert record['attempts'][-1]['correction_budget_exhausted'] is True
    assert record['attempts'][-1]['corrective_kind'] == 'draft_output'
    assert 'draft' not in record and 'review' not in record and 'status' not in record
    assert context == original


def test_schema_then_repeated_ineligible_binding_never_becomes_automatic_unknown():
    result, invalid, malformed, _, _, _ = ratio_outputs()
    gateway = ScriptedGateway([malformed, invalid, invalid])
    context, record = _context(result), dict(attempts=[])
    original = deepcopy(context)
    with pytest.raises(ValueError, match='binding_validation correction budget exhausted'):
        _review_batch(gateway, context, record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft] * 3
    assert all(not entry['draft']['unresolved_observation_ids']
               for entry in record['attempts'] if 'draft' in entry)
    assert 'review' not in record and 'draft' not in record and 'status' not in record
    assert context == original


def test_three_draft_cap_still_blocks_a_first_semantic_correction_after_other_repairs():
    result, invalid, malformed, unknown, _, rejected = ratio_outputs()
    gateway = ScriptedGateway([malformed, invalid, unknown, rejected])
    context, record = _context(result), dict(attempts=[])
    original = deepcopy(context)
    with pytest.raises(ValueError, match='independent_review correction budget exhausted'):
        _review_batch(gateway, context, record)
    assert [call[1] for call in gateway.calls] == [AuditScopeDraft] * 3 + [AuditScopeReview]
    assert len(record['attempts']) == record['correction_limits']['max_drafts'] == 3
    assert record['attempts'][-1]['review']['unresolved_accepted'] is False
    assert record['attempts'][-1]['correction_budget_exhausted'] is True
    assert 'draft' not in record and 'review' not in record and 'status' not in record
    assert context == original


def test_real_gateway_schema_repair_preserves_source_and_independent_review():
    from tests.test_budget_output_v145 import gateway as real_gateway
    result, invalid, malformed, unknown, accepted, _ = ratio_outputs()
    gateway, client = real_gateway([malformed.response, response(invalid),
                                   response(unknown), response(accepted)])
    context, record = _context(result), dict(attempts=[])
    original = deepcopy(context)
    _review_batch(gateway, context, record)
    assert len(client.requests) == 4 and record['status'] == 'complete'
    assert record['attempts'][0]['draft_output_attempts'][0]['status'] == 'invalid_format'
    assert record['attempts'][0]['format_failure']['raw_response'] == malformed.response.text
    assert record['corrections_used'] == dict(draft_output=1, binding_validation=1,
        independent_review=0, review_output=0)
    assert_ratio_contract(client.requests[0][0])
    assert_ratio_contract(client.requests[1][0])
    assert context == original


def test_truncated_draft_does_not_borrow_any_content_correction():
    from tests.test_budget_output_v145 import gateway as real_gateway
    result, _, _, _, _, _ = ratio_outputs()
    gateway, client = real_gateway([response('{"bindings":', finish='length')] * 2)
    record = dict(attempts=[])
    with pytest.raises(LLMStructuredOutputError):
        _review_batch(gateway, _context(result), record)
    assert len(client.requests) == 2
    assert client.requests[0][0] == client.requests[1][0]
    assert len(record['attempts']) == 1
    assert record['corrections_used'] == dict(draft_output=0, binding_validation=0,
        independent_review=0, review_output=0)
    assert 'format_failure' not in record['attempts'][0]
    assert 'status' not in record
