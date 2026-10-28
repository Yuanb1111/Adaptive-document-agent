"""Navigation capacity exhaustion cannot masquerade as an empty source selection."""
import json
from copy import deepcopy
import pytest

from adaptive_document_agent.agent.report_audit_scope import review_report_audit_scope
from adaptive_document_agent.agent.report_audit_source_discovery import discover_audit_sources, validate_audit_source_discovery
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_audit_source_format_correction_v177 import case
from tests.test_budget_output_v145 import gateway, response


def exhausted(limit):
    value = response('', finish='length')
    value.usage.output_tokens = value.usage.reasoning_tokens = limit
    return value


def test_empty_reasoning_response_retries_complete_navigation_then_validates_full_pages():
    result, base, valid = case()
    before = deepcopy((result, base))
    llm, client = gateway([exhausted(16384), response(valid)])
    audit = {}
    expanded = discover_audit_sources(llm, result, base, audit)
    assert [kw['max_tokens'] for _, kw in client.requests] == [16384, 32768]
    assert client.requests[0][0] == client.requests[1][0]
    assert expanded['source_pages'][-1]['text'] == result.document.pages[-1].text
    validate_audit_source_discovery(result, expanded, audit['source_discovery'])
    physical = audit['source_discovery']['attempts'][0]['selection_output_attempts'][0]
    assert physical['response_chars'] == 0 and physical['usage']['reasoning_tokens'] == 16384
    assert (result, base) == before


def test_both_output_limits_exhausted_save_retry_diagnostics_without_starting_audit():
    result, _, _ = case()
    before = deepcopy((result.document, result.observations, result.analysis_results))
    llm, client = gateway([exhausted(16384), exhausted(32768)])
    with pytest.raises(LLMStructuredOutputError):
        review_report_audit_scope(llm, result)
    record = json.loads(result.validation_warnings[-1].message)
    discovery = record['source_discovery']
    assert discovery['failure_kind'] == 'output_capacity_exhausted'
    assert discovery['status'] == 'failed' and 'selection' not in discovery
    assert record['batches'] == [] and len(client.requests) == 2
    assert len(discovery['attempts']) == 1
    assert (result.document, result.observations, result.analysis_results) == before


def test_larger_response_cannot_approve_an_invented_source_range():
    result, base, valid = case()
    invalid = valid.model_copy(deep=True)
    invalid.ranges[0].section_id = 'invented'
    llm, client = gateway([exhausted(16384), response(invalid), response(invalid)])
    audit = {}
    with pytest.raises(ValueError, match='indexed section'):
        discover_audit_sources(llm, result, base, audit)
    assert len(client.requests) == 3
    assert audit['source_discovery']['status'] == 'failed'
    assert 'selection' not in audit['source_discovery']
