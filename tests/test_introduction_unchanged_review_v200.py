"""An unchanged repair requires an explicit model decision and fresh semantic review."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_meaning_resolution import MeaningResolutionEdit
from adaptive_document_agent.agent.introduction_unchanged_review import UnchangedMeaningDecision
from adaptive_document_agent.agent.introduction_audience_review import review_current_selection
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from tests.introduction_review_helpers import review_response
from tests.test_introduction_resolution_feedback_v181 import fixture, Replies, resolve


def unchanged_fixture():
    values = fixture()
    selection, rejected = values[2], values[4]
    rejected.edits = [MeaningResolutionEdit(meaning_id='part-0:meaning-1',
        required_meanings=[deepcopy(selection.decisions[0].required_meanings[0])])]
    rejected.finding_dispositions[0].referenced_meaning_ids = ['part-0:meaning-1']
    return values


def decision(action='already_covered', **overrides):
    fields = dict(finding_id='finding-0', meaning_id='part-0:meaning-1', action=action,
                  reason='Explicit synthetic judgment of the current source-owned assertion.')
    fields.update(overrides)
    return UnchangedMeaningDecision(**fields)


@pytest.mark.parametrize('action', ['already_covered', 'revise'])
def test_unchanged_correction_gets_narrow_adjudication_with_source_and_protected_copy(action):
    values = unchanged_fixture()
    reading, source, selection, verdict, rejected, corrected = values
    answer = decision(action, required_meanings=(corrected.edits[0].required_meanings if action == 'revise' else []))
    original = deepcopy((source, selection, verdict, rejected))
    client = Replies(rejected, answer)
    draft, ledger = resolve(client, values)
    assert len(client.messages) == 2 and client.messages[1][:2] == client.messages[0]
    assert client.messages[1][3]['role'] == 'system'
    assert 'Return only UnchangedMeaningDecision' in client.messages[1][3]['content']
    context = json.loads(client.messages[1][2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert context['current_meaning'] == context['proposed_meaning']
    assert (source, selection, verdict, rejected) == original
    assert draft.decisions[0].required_meanings[1:] == selection.decisions[0].required_meanings[1:]
    assert (draft == selection) is (action == 'already_covered')
    assert ledger['finding_dispositions'][0]['action'] == ('corrected' if action == 'revise' else action)
    assert ledger['semantic_approval'] is False and not reading.audience_selection
    rows = reading.plan_audits[-1]['introduction_meaning_resolution']['protocol_attempts']
    assert rows[0]['response'] == rejected.model_dump(mode='json')
    assert rows[1]['response'] == answer.model_dump(mode='json')
    assert rows[1]['status'] == 'protocol_validated' and rows[1]['semantic_approval'] is False


@pytest.mark.parametrize('fault', ['wrong_finding', 'wrong_meaning', 'unchanged', 'empty', 'covered_with_edit', 'privacy'])
def test_invalid_adjudication_never_adds_retries_or_changes_the_selection(fault):
    values = unchanged_fixture()
    answer = decision()
    if fault == 'wrong_finding': answer.finding_id = 'unknown'
    elif fault == 'wrong_meaning': answer.meaning_id = 'part-0:meaning-2'
    elif fault in {'unchanged', 'empty'}:
        answer.action = 'revise'
        answer.required_meanings = [] if fault == 'empty' else values[4].edits[0].required_meanings
    elif fault == 'covered_with_edit': answer.required_meanings = values[5].edits[0].required_meanings
    else: answer = PrivacyViolationError('Local Only')
    original = deepcopy(values[2])
    client = Replies(values[4], answer)
    with pytest.raises((ValueError, PrivacyViolationError)):
        resolve(client, values)
    assert len(client.messages) == 2 and values[2] == original
    assert not values[0].audience_selection


@pytest.mark.parametrize('accepted', [False, True])
def test_model_disagreement_is_still_adjudicated_by_fresh_independent_review(accepted):
    values = unchanged_fixture()
    reading, source, selection = values[:3]
    draft, ledger = resolve(Replies(values[4], decision()), values)
    class Reviewer:
        def generate_structured(self, messages, schema, **kwargs):
            return review_response(schema, messages, accepted=accepted, repair_scope='meanings',
                reason='Fresh independent judgment of the entire source and the disputed finding.')
    verdict = review_current_selection(Reviewer(), source, draft.model_dump(mode='json')['decisions'],
        'Independently review all findings.', reading, attempt=2,
        meaning_revision_base=selection.model_dump(mode='json')['decisions'],
        inventory_revision_base=None, binding_budget={'used': False}, meaning_resolution=ledger)
    assert verdict.accepted is accepted
    assert not reading.audience_selection and ledger['semantic_approval'] is False


def test_adjudication_preserves_another_real_correction_and_its_disposition():
    from adaptive_document_agent.agent.introduction_audience_review import IntroductionReviewFinding
    from adaptive_document_agent.agent.introduction_meaning_resolution import FindingDisposition
    values = unchanged_fixture()
    selection, verdict, proposal = values[2:5]
    original = selection.decisions[0].required_meanings[1]
    verdict.findings.append(IntroductionReviewFinding(kind='meaning', issue_type='missing_qualification',
        part_id='part-0', meaning_id='part-0:meaning-2', current_meaning=original.meaning,
        source_quote=values[1]['parts'][0]['source_text'], reason='Synthetic second finding.'))
    edit = MeaningResolutionEdit(meaning_id='part-0:meaning-2',
        required_meanings=[dict(meaning=original.meaning + ' Staff training is required.')])
    disposition = FindingDisposition(finding_id='finding-1', classification='missing_qualification',
        action='corrected', referenced_meaning_ids=['part-0:meaning-2'], reason='A separate proposed correction.')
    proposal.edits.append(edit)
    proposal.finding_dispositions.append(disposition)
    before = deepcopy(proposal)
    draft, ledger = resolve(Replies(proposal, decision()), values)
    assert proposal == before
    assert draft.decisions[0].required_meanings[1] == edit.required_meanings[0]
    retained = ledger['finding_dispositions'][1]
    assert all(retained[k] == getattr(disposition, k) for k in
               ['finding_id', 'classification', 'action', 'referenced_meaning_ids', 'reason'])


def test_cancellation_before_adjudication_stops_without_a_second_model_call():
    from threading import Event
    from concurrent.futures import CancelledError
    values, signal = unchanged_fixture(), Event()
    class Client(Replies):
        def generate_structured(self, *args, **kwargs):
            result = super().generate_structured(*args, **kwargs)
            signal.set()
            return result
    client = Client(values[4])
    with pytest.raises(CancelledError):
        resolve(client, values, signal)
    assert len(client.messages) == 1 and not values[0].audience_selection
