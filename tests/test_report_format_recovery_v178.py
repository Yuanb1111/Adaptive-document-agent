"""Complete malformed report replies get bounded corrections, never approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_integration_review import (
    SOURCE_OUTPUT_TOKEN_LIMITS, review_supplementary_sources, resolved_source_check_ids,
)
from adaptive_document_agent.agent.report_audit_scope import _context, _review_batch
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMTransportError, PrivacyViolationError
from tests.test_budget_output_v145 import gateway, response
from tests.test_source_completion_capacity_v173 import _outputs, _audit
from tests.test_source_integration_v166 import fixture
from tests.test_report_audit_scope_v174 import fixture as audit_fixture
from tests.test_audit_review_contract_v174 import unknown_draft, unknown_review


@pytest.mark.parametrize('finish', ['stop', None])
@pytest.mark.parametrize('role', ['draft', 'review'])
def test_overlong_or_missing_field_is_corrected_with_complete_original_context(role, finish):
    result, constraint = fixture()
    original = deepcopy(result.executive_brief)
    source = deepcopy((result.document, result.observations))
    draft, review = _outputs(constraint)
    invalid = draft.model_dump()
    invalid['additions'][0]['text'] = 'x' * 578
    raw = json.dumps(invalid) if role == 'draft' else '{"verdicts":[{"section_id":"contracts","accepted":true}]}'
    outputs = ([response(raw, finish=finish), response(draft), response(review)] if role == 'draft'
               else [response(draft), response(raw, finish=finish), response(review)])
    llm, client = gateway(outputs)
    result.executive_brief = review_supplementary_sources(llm, result, original)
    assert len(client.requests) == 3
    start = 0 if role == 'draft' else 1
    first, retry = client.requests[start][0], client.requests[start+1][0]
    assert retry[:len(first)] == first
    feedback = json.loads(retry[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert feedback['raw_response'] == raw
    assert feedback['schema_errors'][0]['loc'] == (['additions', 0, 'text'] if role == 'draft' else ['verdicts', 0, 'reason'])
    # Format correction stays on the initial capacity; only length exhaustion
    # can consume the larger capacity retry tested separately.
    assert all(r[1]['max_tokens'] == SOURCE_OUTPUT_TOKEN_LIMITS[0] for r in client.requests)
    assert result.executive_brief.items[0] == original.items[0]
    assert result.executive_brief.items[1:] == draft.additions
    assert resolved_source_check_ids(result, result.executive_brief) == {'contracts'}
    assert (result.document, result.observations) == source
    code, audit = _audit(result)
    assert code == 'source_integration_review'
    assert raw == audit['attempts'][0][f'{role}_output_attempts'][0]['raw_response']
    assert len(audit['attempts']) == (2 if role == 'draft' else 1)


@pytest.mark.parametrize('role', ['draft', 'review'])
def test_repeated_format_error_leaves_original_brief_and_unresolved_checkpoint(role):
    result, constraint = fixture()
    draft, _ = _outputs(constraint)
    outputs = ([] if role == 'draft' else [response(draft)]) + [response('{}')] * 2
    llm, client = gateway(outputs)
    original = deepcopy(result.executive_brief)
    assert review_supplementary_sources(llm, result, original) == original
    assert len(client.requests) == len(outputs)
    assert not resolved_source_check_ids(result, original)
    assert _audit(result)[0] == 'source_integration_unresolved'


@pytest.mark.parametrize('role', ['draft', 'review'])
@pytest.mark.parametrize('error', [LLMTransportError('Offline'), PrivacyViolationError('Local Only')])
def test_transport_and_privacy_errors_never_trigger_format_regeneration(role, error):
    result, constraint = fixture()
    draft, _ = _outputs(constraint)
    outputs = ([] if role == 'draft' else [response(draft)]) + [error]
    llm, client = gateway(outputs)
    original = deepcopy(result.executive_brief)
    if isinstance(error, PrivacyViolationError):
        with pytest.raises(PrivacyViolationError):
            review_supplementary_sources(llm, result, original)
    else:
        assert review_supplementary_sources(llm, result, original) == original
    assert len(client.requests) == len(outputs)
    assert not resolved_source_check_ids(result, original)


def test_reviewer_id_correction_keeps_same_draft_and_does_not_discard_semantic_rejection():
    result, constraint = fixture()
    draft, review = _outputs(constraint)
    rejected = review.model_copy(deep=True)
    rejected.verdicts[0].accepted = False
    llm, client = gateway([response(draft), response('{"verdicts":[]}'), response(rejected),
                           response(draft), response('{"verdicts":[]}')])
    original = deepcopy(result.executive_brief)
    assert review_supplementary_sources(llm, result, original) == original
    assert len(client.requests) == 5
    assert client.requests[2][0][:len(client.requests[1][0])] == client.requests[1][0]
    code, audit = _audit(result)
    assert code == 'source_integration_unresolved'
    assert audit['corrections_used']['review_format'] == 1
    assert audit['attempts'][0]['review']['verdicts'][0]['accepted'] is False


def test_draft_format_correction_cannot_bypass_literal_evidence_or_borrow_semantic_retry():
    result, constraint = fixture()
    draft, _ = _outputs(constraint)
    draft.decisions[0].evidence[0].text = 'Invented source quotation.'
    llm, client = gateway([response('{}'), response(draft)])
    original = deepcopy(result.executive_brief)
    assert review_supplementary_sources(llm, result, original) == original
    assert len(client.requests) == 2
    assert 'literal quotation' in _audit(result)[1]['reason']


@pytest.mark.parametrize('recover', [True, False])
def test_audit_writer_format_error_preserves_binding_validation_budget(recover):
    result, _ = audit_fixture()
    invalid = '{"unexpected":true}'
    outputs = [response(invalid), response(unknown_draft()) if recover else response(invalid)]
    if recover:
        outputs.append(response(unknown_review()))
    llm, client = gateway(outputs)
    context = _context(result)
    original = deepcopy(context)
    record = dict(attempts=[])
    if recover:
        _review_batch(llm, context, record)
        assert record['status'] == 'complete'
    else:
        with pytest.raises(ValueError, match='draft_output correction budget exhausted') as failure:
            _review_batch(llm, context, record)
        assert isinstance(failure.value.__cause__, LLMStructuredOutputError)
        assert 'unexpected' in str(failure.value)
        assert record.get('status') != 'complete'
    assert len(client.requests) == len(outputs)
    assert record['corrections_used']['draft_output'] == 1
    assert record['corrections_used']['binding_validation'] == 0
    assert record['corrections_used']['independent_review'] == 0
    assert record['attempts'][0]['format_failure']['raw_response'] == invalid
    assert context == original
