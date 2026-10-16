"""Bound historical context informs a fresh reviewer without approving current copy."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_audience_review import review_current_selection
from adaptive_document_agent.agent.introduction_review_history import (
    decision_references, prior_bound_history, resolution_wire, review_context_identity,
)
from tests.introduction_review_helpers import review_response
from tests.test_introduction_review_binding_v143 import review_context
from tests.test_introduction_meaning_resolution_v147 import resolution_fixture


RULES = 'Review the entire current source for a short business introduction; detailed analyses may stay later.'


def raw_payload(messages):
    return json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


def review_once(reading, payload, budget, response, *, attempt=0, source=None, rules=RULES):
    requests = []
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            requests.append(deepcopy(messages))
            return response(schema, messages)
    verdict = review_current_selection(Client(), source or payload['source'], payload['decisions'],
        rules, reading, attempt=attempt, meaning_revision_base=None, inventory_revision_base=None,
        binding_budget=budget)
    return verdict, requests


def reject_current(schema, messages):
    payload = raw_payload(messages)
    target = payload['current_meanings'][0]
    source = next(part for part in payload['source']['parts'] if part['id'] == target['part_id'])
    return review_response(schema, messages, accepted=False, repair_scope='meanings',
        reason='The named assertion still needs its source qualification; detailed risks may stay in later analysis.',
        findings=[dict(kind='meaning', issue_type='missing_qualification', part_id=target['part_id'],
            meaning_id=target['meaning_id'], current_meaning=target['meaning'],
            source_quote=source['source_text'], reason='Keep the source qualification with the selected assertion.')])


def test_same_context_new_background_finding_has_prior_scope_and_requires_section_reason():
    reading, payload = review_context()
    budget = {'used': False}
    review_once(reading, payload, budget, reject_current)
    original = deepcopy(reading.plan_audits)
    def newly_required_risk(schema, messages):
        wire = raw_payload(messages)
        history = wire['prior_bound_reviews']
        assert len(history) == 1
        assert history[0]['source_and_section_context_unchanged']
        assert history[0]['scope_deltas'] == []
        assert 'detailed risks may stay' in history[0]['reason']
        assert history[0]['semantic_approval_for_current_selection'] is False
        assert 'why an earlier same-source relevance judgment needs' in messages[0]['content']
        assert 'A necessary qualifier of a selected assertion must still be preserved' in messages[0]['content']
        omitted = wire['decisions'][1]['part_id']
        source = next(p for p in wire['source']['parts'] if p['id'] == omitted)
        reason = ('This risk is essential to this section because it limits the stated service availability; '
                  'the earlier decision to defer it left that selected scope misleading.')
        return review_response(schema, messages, accepted=False, repair_scope='selection', reason=reason,
            findings=[dict(kind='omitted_part', issue_type='new_assertion', part_id=omitted,
                source_quote=source['source_text'], reason=reason)])
    verdict, requests = review_once(reading, payload, budget, newly_required_risk, attempt=1)
    assert not verdict.accepted and len(requests) == 1
    assert 'essential to this section' in verdict.findings[0].reason
    assert reading.plan_audits[:len(original)] == original
    assert not reading.audience_selection and reading.audience_part_ids is None


def test_past_bound_acceptance_never_immunizes_a_true_missing_qualifier():
    reading, payload = review_context()
    budget = {'used': False}
    review_once(reading, payload, budget, lambda schema, messages: review_response(
        schema, messages, accepted=True, reason='A previous synthetic reviewer accepted this scope.'))
    verdict, requests = review_once(reading, payload, budget, reject_current, attempt=1)
    assert not verdict.accepted and len(requests) == 1
    history = raw_payload(requests[0])['prior_bound_reviews']
    assert history[0]['accepted'] is True
    assert history[0]['semantic_approval_for_current_selection'] is False
    assert verdict.findings[0].issue_type == 'missing_qualification'


@pytest.mark.parametrize('fault', ['unbound', 'no_identity', 'other_flow', 'other_context',
    'changed_digest', 'changed_verdict_digest', 'stale_finding', 'foreign_quote'])
def test_only_same_flow_exactly_bound_history_is_exposed(fault):
    reading, payload = review_context()
    budget = {'used': False}
    review_once(reading, payload, budget, reject_current)
    record = reading.plan_audits[-1]['introduction_audience_review']
    if fault == 'unbound': record['status'] = 'invalid_binding'
    elif fault == 'no_identity': record.pop('context_identity')
    elif fault == 'other_flow': record['flow_id'] = 'another invocation'
    elif fault == 'other_context': record['context_identity']['context_digest'] = 'another section'
    elif fault == 'changed_digest': record['selection_digest'] = 'different selection'
    elif fault == 'changed_verdict_digest': record['review']['selection_digest'] = 'stale draft'
    elif fault == 'stale_finding': record['review']['findings'][0]['current_meaning'] = 'Stale assertion.'
    else: record['review']['findings'][0]['source_quote'] = 'Not in the actual owned source.'
    _, requests = review_once(reading, payload, budget, reject_current, attempt=1)
    assert raw_payload(requests[0])['prior_bound_reviews'] == []


@pytest.mark.parametrize('change', ['source', 'purpose', 'budget', 'rules'])
def test_changed_source_or_audience_context_cannot_supply_an_old_scope_precedent(change):
    reading, payload = review_context()
    payload['source']['document_purpose'] = 'Explain the disclosed business.'
    budget = {'used': False}
    review_once(reading, payload, budget, reject_current)
    source, rules = deepcopy(payload['source']), RULES
    if change == 'source':
        reading.parts[0].source_text += ' New source condition.'
        source['parts'][0]['source_text'] += ' New source condition.'
    elif change == 'purpose': source['document_purpose'] = 'Explain safety conditions for operators.'
    elif change == 'budget': reading.max_intro_slides = 2
    else: rules += ' Include a complete risk assessment in this section.'
    _, requests = review_once(reading, payload, budget, reject_current, attempt=1, source=source, rules=rules)
    assert raw_payload(requests[0])['prior_bound_reviews'] == []


def test_history_uses_owned_source_references_and_exact_current_copy_links_without_duplication():
    reading, payload = review_context()
    budget = {'used': False}
    review_once(reading, payload, budget, reject_current)
    identity = review_context_identity(payload['source'], RULES, reading)
    history = prior_bound_history(reading, payload['source'], payload['decisions'], identity,
                                  budget['review_flow_id'])
    row = history[0]['findings'][0]
    assert row['source_part_ref'] == payload['decisions'][0]['part_id']
    assert row['source_normalized_span'][0] == 0
    assert row['exact_current_meaning_ids'] == [row['historical_meaning_id']]
    assert row['current_part_copy_unchanged'] is True
    serialized = json.dumps(history)
    assert 'source_quote' not in serialized and 'source_text' not in serialized
    assert 'decisions' not in serialized


def test_resolution_wire_has_one_immutable_before_copy_and_exact_per_part_references():
    _, _, _, selection, _, _ = resolution_fixture()
    from adaptive_document_agent.agent.introduction_audience_review import current_meanings
    decisions = selection.model_dump(mode='json')['decisions']
    rows = [{k: v for k, v in row.items() if k != 'source_quote'} for row in current_meanings(decisions)]
    ledger = dict(reference_namespace='before_resolution_meanings', before_resolution_meanings=rows,
                  decisions_before=decisions, finding_dispositions=[])
    before = deepcopy(ledger)
    wire = resolution_wire(ledger)
    assert ledger == before
    assert wire['reference_namespace'] == wire['decisions_before_namespace'] == 'before_resolution_meanings'
    assert wire['before_resolution_meanings'] == rows
    assert wire['decisions_before'][0]['required_meaning_ids'] == [row['meaning_id'] for row in rows]
    assert 'required_meanings' not in wire['decisions_before'][0]
    assert wire['decisions_before'][1]['required_meaning_ids'] == []
    assert json.dumps(wire).count(rows[0]['meaning']) == 1


def test_current_wire_has_exact_ordered_ids_and_the_canonical_selection_digest():
    from adaptive_document_agent.services.introduction_audience import selection_digest
    reading, payload = review_context()
    before = deepcopy(payload['decisions'])
    _, requests = review_once(reading, payload, {'used': False}, reject_current)
    wire = raw_payload(requests[0])
    assert wire['decisions_reference_namespace'] == 'current_meanings'
    assert wire['current_selection_digest'] == selection_digest(reading, before)
    assert wire['decisions'][0]['required_meaning_ids'] == [wire['current_meanings'][0]['meaning_id']]
    assert wire['decisions'][1]['required_meaning_ids'] == []
    assert all('required_meanings' not in decision for decision in wire['decisions'])
    assert payload['decisions'] == before


@pytest.mark.parametrize('fault', ['reordered_copy', 'wrong_part', 'wrong_index', 'duplicate_id',
    'missing_meaning', 'extra_meaning', 'duplicate_decision'])
def test_current_reference_compression_cannot_change_or_lose_any_assertion(fault):
    from adaptive_document_agent.agent.introduction_audience_review import current_meanings
    _, _, _, selection, _, _ = resolution_fixture()
    decisions = selection.model_dump(mode='json')['decisions']
    rows = current_meanings(decisions)
    if fault == 'reordered_copy':
        decisions[0]['required_meanings'] = list(reversed(decisions[0]['required_meanings']))
    elif fault == 'wrong_part': rows[0]['part_id'] = 'part-1'
    elif fault == 'wrong_index': rows[0]['meaning_index'] = 999
    elif fault == 'duplicate_id': rows.append(deepcopy(rows[0]))
    elif fault == 'missing_meaning': rows.pop()
    elif fault == 'extra_meaning':
        rows.append(dict(meaning_id='part-1:meaning-1', part_id='part-1', meaning_index=0, meaning='Extra assertion.'))
    else: decisions.append(deepcopy(decisions[0]))
    with pytest.raises(ValueError):
        decision_references(decisions, rows)


@pytest.mark.parametrize('fault', ['different_text', 'different_owner', 'duplicate_id'])
def test_resolution_wire_never_reinterprets_stale_or_foreign_before_namespace(fault):
    _, _, _, selection, _, _ = resolution_fixture()
    from adaptive_document_agent.agent.introduction_audience_review import current_meanings
    decisions = selection.model_dump(mode='json')['decisions']
    rows = current_meanings(decisions)
    if fault == 'different_text': rows[0]['meaning'] = 'Different assertion.'
    elif fault == 'different_owner': rows[0]['part_id'] = 'part-1'
    else: rows.append(deepcopy(rows[0]))
    with pytest.raises(ValueError):
        resolution_wire(dict(reference_namespace='before_resolution_meanings',
            before_resolution_meanings=rows, decisions_before=decisions))
