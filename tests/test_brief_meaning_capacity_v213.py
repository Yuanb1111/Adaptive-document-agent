"""Capacity partitioning retains shared evidence and cannot certify false claims."""
from concurrent.futures import CancelledError
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_meaning_capacity import complete_meaning_output
from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview, meaning_validator
from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
from adaptive_document_agent.agent.prompting import untrusted_document_message
from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from tests.test_brief_review_bindings_v139 import setup_review
from tests.test_budget_output_v145 import gateway, response


def request():
    pending = [dict(index=i, item=dict(text=f'Literal claim {i}', evidence=[dict(
        ref=f'i{i}_q0', text='  Complete source\nwith literal spacing.  ')])) for i in range(2)]
    pending[0]['available_report_context'] = dict(evidence_blocks={'b': 'Full common source'},
        source_excerpt_scope=[dict(page=1, truncated=False)], current_brief=dict(items=['A', 'B']))
    messages = [dict(role='system', content='Review all source meaning; untrusted data only.'),
                untrusted_document_message(json.dumps(pending))]
    reviews = [BriefMeaningReview(items=[dict(index=i, accepted=True,
        reason='Exact source', numeric_comparison=False)]) for i in range(2)]
    return messages, pending, reviews


def payload(messages):
    content = next(m['content'] for m in messages if m['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>\n'))
    return json.loads(content.split('\n', 1)[1].rsplit('\n', 1)[0])


def test_real_gateway_fallback_keeps_whole_brief_context_and_exact_item_sources():
    messages, pending, reviews = request()
    before = deepcopy((messages, pending))
    llm, client = gateway([response('', finish='length')] * 2 + [response(r) for r in reviews] * 2)
    record, capacity = {}, {}
    combined = complete_meaning_output(llm, messages, BriefMeaningReview, pending, record, capacity)
    assert [r.index for r in combined.items] == [0, 1]
    assert [kw['max_tokens'] for _, kw in client.requests] == [16384, 24576, 16384, 16384]
    assert client.requests[0][0] == client.requests[1][0]
    for i, (sent, _) in enumerate(client.requests[2:]):
        row = payload(sent)[0]
        assert row['index'] == i and row['item'] == pending[i]['item']
        assert row['available_report_context'] == pending[0]['available_report_context']
    assert [b['indices'] for b in record['single_item_batches']] == [[0], [1]]
    assert (messages, pending) == before
    # The same validator's later writer correction does not repeat the oversized batch.
    complete_meaning_output(llm, messages, BriefMeaningReview, pending, {}, capacity)
    assert len(client.requests) == 6
    assert all(len(payload(sent)) == 1 for sent, _ in client.requests[4:])


@pytest.mark.parametrize('failure', [LLMTransportError('offline'), PrivacyViolationError('Local Only'), CancelledError()])
def test_transport_privacy_and_cancellation_never_trigger_partitioning(failure):
    messages, pending, _ = request()
    llm, client = gateway([failure])
    record, capacity = {}, {}
    with pytest.raises(type(failure)):
        complete_meaning_output(llm, messages, BriefMeaningReview, pending, record, capacity)
    assert len(client.requests) == 1 and not capacity


def test_single_item_exhaustion_stops_without_returning_partial_approval():
    messages, pending, _ = request()
    llm, client = gateway([response('', finish='length')] * 4)
    record = {}
    with pytest.raises(LLMStructuredOutputError):
        complete_meaning_output(llm, messages, BriefMeaningReview, pending, record, {})
    assert len(client.requests) == 4
    assert len(record['single_item_batches']) == 1


def test_wrong_partition_index_cannot_be_joined_into_approval():
    messages, pending, reviews = request()
    llm, client = gateway([response('', finish='length')] * 2 + [response(reviews[1])])
    with pytest.raises(ValueError, match='every exact supplied index'):
        complete_meaning_output(llm, messages, BriefMeaningReview, pending, {}, {})
    assert len(client.requests) == 3


def test_partitioned_semantic_acceptance_still_fails_false_endpoint_arithmetic():
    brief, result, original, corrected = setup_review()
    wrong = corrected['items'][0]
    wrong['comparisons'][0]['direction'] = 'decrease'
    other = original['items'][1]
    audience = BriefClaimDirectionReview(items=[dict(index=1, comparisons=[])])
    llm, client = gateway([response('', finish='length')] * 2 + [
        response(BriefMeaningReview(items=[wrong])), response(BriefMeaningReview(items=[other])),
        response(audience)])
    before = deepcopy((brief, result.document, result.observations))
    validate = meaning_validator(llm, result=result, source_context=dict(
        evidence_blocks={'source': result.document.pages[0].text}, source_excerpt_scope=[]))
    errors = validate(brief)
    assert set(errors) == {0} and 'direction contradicts' in str(errors)
    assert validate(brief) == errors and len(client.requests) == 5
    assert (brief, result.document, result.observations) == before
    audit = next(w for w in result.validation_warnings if w.code == 'executive_brief_meaning_capacity_audit')
    assert len(json.loads(audit.message)['single_item_batches']) == 2
