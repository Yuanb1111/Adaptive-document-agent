"""Source discovery repairs complete malformed replies without bypassing evidence gates."""
from concurrent.futures import CancelledError
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.report_audit_scope import _context, review_report_audit_scope
from adaptive_document_agent.agent.report_audit_source_discovery import (
    AuditSourceDiscovery, discover_audit_sources, validate_audit_source_discovery,
)
from adaptive_document_agent.agent.report_audit_source_index import discovery_input
from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from tests.test_audit_source_discovery_v174 import unread_case
from tests.test_budget_output_v145 import gateway, response


def case():
    result = unread_case()
    base = _context(result)
    payload, _ = discovery_input(result, base)
    valid = AuditSourceDiscovery(ranges=[dict(section_id=payload['sections'][0]['id'],
        start_page=8, end_page=9, observation_ids=['amount'],
        reason='Read the counterpart amount with its complete header and units.')],
        rationale='Locate exact source counterparts without assigning assurance.')
    return result, base, valid


@pytest.mark.parametrize('kind', ['missing_rationale', 'extra_field', 'invalid_json', 'no_json'])
def test_real_gateway_corrects_schema_with_full_context_and_raw_failure_retained(kind):
    result, base, valid = case()
    original = deepcopy((result, base))
    raw = valid.model_dump()
    if kind == 'missing_rationale':
        del raw['rationale']
    elif kind == 'extra_field':
        raw['unexpected'] = 'not part of the contract'
    raw = json.dumps(raw) if kind != 'invalid_json' else '{"ranges": invalid}'
    if kind == 'no_json':
        raw = 'No structured response was provided.'
    llm, client = gateway([response(raw), response(valid)])
    audit = {}
    expanded = discover_audit_sources(llm, result, base, audit)
    assert len(client.requests) == 2
    first, corrected = [r[0] for r in client.requests]
    assert corrected[:len(first)] == first  # Includes the gateway schema and complete source input.
    assert raw in json.loads(corrected[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])['raw_response']
    attempts = audit['source_discovery']['attempts']
    assert len(attempts) == 2
    assert attempts[0]['selection_output_attempts'][0]['raw_response'] == raw
    assert attempts[0]['selection_output_attempts'][0]['status'] == 'invalid_format'
    if kind == 'no_json':
        assert 'JSON object or array' in attempts[0]['correction_feedback']['schema_error']
    else:
        assert attempts[0]['correction_feedback']['schema_errors']
    if kind == 'missing_rationale':
        assert attempts[0]['correction_feedback']['schema_errors'][0]['loc'] == ('rationale',)
    assert 'selection' not in attempts[0]
    assert audit['source_discovery']['selection'] == valid.model_dump(mode='json')
    assert expanded['source_pages'][-1]['text'] == result.document.pages[-1].text
    validate_audit_source_discovery(result, expanded, audit['source_discovery'])
    assert (result, base) == original
    assert 'draft' not in audit and 'review' not in audit


@pytest.mark.parametrize('order', ['format_format', 'format_source', 'source_format'])
def test_format_and_source_errors_share_one_correction_and_save_failed_checkpoint(order):
    result, _, valid = case()
    original = deepcopy((result.document, result.observations))
    invalid = valid.model_copy(deep=True)
    invalid.ranges[0].section_id = 'invented'
    outputs = {'format': response('{"ranges":[]}'), 'source': response(invalid)}
    llm, client = gateway([outputs[key] for key in order.split('_')])
    with pytest.raises((LLMStructuredOutputError, ValueError)):
        review_report_audit_scope(llm, result)
    assert len(client.requests) == 2
    warning = result.validation_warnings[-1]
    assert warning.code == 'report_audit_scope_unresolved'
    audit = json.loads(warning.message)
    record = audit['source_discovery']
    assert record['status'] == 'failed' and audit['batches'] == []
    assert len(record['attempts']) == 2
    assert record['attempts'][-1]['correction_budget_exhausted'] is True
    assert (result.document, result.observations) == original


@pytest.mark.parametrize('error', [LLMTransportError('Offline'),
    PrivacyViolationError('Local Only'), CancelledError(), ValueError('Invalid configuration')])
@pytest.mark.parametrize('after_format_error', [False, True])
def test_non_content_failures_propagate_without_extra_calls(error, after_format_error):
    result, base, _ = case()
    outputs = ([response('{"ranges":[]}')] if after_format_error else []) + [error]
    llm, client = gateway(outputs)
    audit = {}
    with pytest.raises(type(error)):
        discover_audit_sources(llm, result, base, audit)
    assert len(client.requests) == len(outputs)
    assert audit['source_discovery']['status'] == 'failed'
    assert 'correction_feedback' not in audit['source_discovery']['attempts'][-1]


def test_exhausted_truncation_never_triggers_format_correction():
    result, base, valid = case()
    llm, client = gateway([response(valid, finish='length')] * 2)
    audit = {}
    with pytest.raises(LLMStructuredOutputError):
        discover_audit_sources(llm, result, base, audit)
    assert [r[1]['max_tokens'] for r in client.requests] == [8192, 16384]
    assert client.requests[0][0] == client.requests[1][0]
    attempts = audit['source_discovery']['attempts']
    assert len(attempts) == 1 and 'correction_feedback' not in attempts[0]
    assert [r['status'] for r in attempts[0]['selection_output_attempts']] == ['truncated'] * 2


def test_capacity_retry_then_complete_format_error_still_has_one_selection_correction():
    result, base, valid = case()
    llm, client = gateway([response('{"ranges":', finish='length'),
                           response('{"ranges":[]}'), response(valid)])
    audit = {}
    discover_audit_sources(llm, result, base, audit)
    assert [r[1]['max_tokens'] for r in client.requests] == [8192, 16384, 8192]
    assert client.requests[0][0] == client.requests[1][0]
    assert len(audit['source_discovery']['attempts']) == 2
    assert audit['source_discovery']['status'] == 'complete'
