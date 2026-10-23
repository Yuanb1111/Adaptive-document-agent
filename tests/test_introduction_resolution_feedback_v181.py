"""A narrative promise cannot repair copy; one concrete correction can be reviewed."""
from copy import deepcopy
import json
from threading import Event
from concurrent.futures import CancelledError

import pytest

from adaptive_document_agent.agent.introduction_audience_review import review_current_selection
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    MeaningResolutionEdit, resolve_meaning_findings)
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from tests.introduction_review_helpers import review_response
from tests.test_introduction_disposition_evidence_v153 import resolve_fixture


def fixture():
    reading, source, selection, verdict, rejected = resolve_fixture()
    row = rejected.finding_dispositions[0]
    row.action, row.classification, row.referenced_meaning_ids = 'corrected', 'missing_qualification', []
    row.reason = 'The assertion is now corrected to retain the training requirement.'
    corrected = rejected.model_copy(deep=True)
    corrected.edits = [MeaningResolutionEdit(meaning_id='part-0:meaning-1', required_meanings=[dict(
        meaning='The system schedules appointments with staff training required before delivery.')])]
    corrected.finding_dispositions[0].referenced_meaning_ids = ['part-0:meaning-1']
    return reading, source, selection, verdict, rejected, corrected


class Replies:
    def __init__(self, *responses):
        self.responses, self.messages = list(responses), []

    def generate_structured(self, messages, schema, **kwargs):
        self.messages.append(deepcopy(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response.model_copy(deep=True)


def resolve(client, values, cancelled=None):
    reading, source, selection, verdict = values[:4]
    return resolve_meaning_findings(client, source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading, cancelled=cancelled)


def test_unapplied_correction_gets_exact_feedback_with_immutable_source_and_raw_audit():
    values = fixture()
    reading, source, selection, verdict, rejected, corrected = values
    before = deepcopy((source, selection, verdict, rejected, corrected))
    client = Replies(rejected, corrected)
    draft, ledger = resolve(client, values)
    assert len(client.messages) == 2
    assert client.messages[1][:2] == client.messages[0]
    feedback = json.loads(client.messages[1][2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert feedback['finding_id'] == 'finding-0'
    assert feedback['required_current_meaning_id'] == 'part-0:meaning-1'
    assert feedback['rejected_proposal'] == rejected.model_dump(mode='json')
    assert 'An action=corrected reason is only an explanation' in client.messages[1][-1]['content']
    assert (source, selection, verdict, rejected, corrected) == before
    assert draft.decisions[0].required_meanings[0] == corrected.edits[0].required_meanings[0]
    assert draft.decisions[0].required_meanings[1:] == selection.decisions[0].required_meanings[1:]
    record = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert [p['response'] for p in record['protocol_attempts']] == [p.model_dump(mode='json') for p in (rejected, corrected)]
    assert record['semantic_approval'] is ledger['semantic_approval'] is False
    assert not reading.audience_selection and reading.audience_part_ids is None


@pytest.mark.parametrize('fault', ['again', 'unknown_id', 'protected_edit', 'no_change', 'missing_disposition'])
def test_second_invalid_proposal_cannot_get_another_retry_or_mutate_selection(fault):
    values = fixture()
    reading, _, selection, _, rejected, corrected = values
    final = corrected.model_copy(deep=True)
    if fault == 'again': final = rejected
    elif fault == 'unknown_id': final.edits[0].meaning_id = 'unknown'
    elif fault == 'protected_edit': final.edits[0].meaning_id = 'part-0:meaning-2'
    elif fault == 'no_change': final.edits[0].required_meanings = [deepcopy(selection.decisions[0].required_meanings[0])]
    else: final.finding_dispositions.clear()
    before = deepcopy(selection)
    client = Replies(rejected, final)
    with pytest.raises(ValueError):
        resolve(client, values)
    assert len(client.messages) == 2 and selection == before
    assert reading.plan_audits[-1]['introduction_meaning_resolution']['status'] == 'failed'
    assert not reading.audience_selection


@pytest.mark.parametrize('during_retry', [False, True])
def test_privacy_failure_is_never_retried_or_replaced(during_retry):
    values = fixture()
    failure = PrivacyViolationError('Local Only')
    client = Replies(*([values[4]] if during_retry else []), failure)
    with pytest.raises(PrivacyViolationError) as caught:
        resolve(client, values)
    assert caught.value is failure and len(client.messages) == 1 + during_retry


def test_cancellation_between_proposals_prevents_retry():
    values = fixture()
    signal = Event()
    class Client(Replies):
        def generate_structured(self, *args, **kwargs):
            result = super().generate_structured(*args, **kwargs)
            signal.set()
            return result
    client = Client(values[4])
    with pytest.raises(CancelledError):
        resolve(client, values, signal)
    assert len(client.messages) == 1
    assert values[0].plan_audits[-1]['introduction_meaning_resolution']['status'] == 'cancelled'


@pytest.mark.parametrize('accepted', [False, True])
def test_concrete_repair_still_needs_fresh_independent_review(accepted):
    values = fixture()
    reading, source, selection, _, rejected, corrected = values
    draft, ledger = resolve(Replies(rejected, corrected), values)
    class Reviewer:
        def generate_structured(self, messages, schema, **kwargs):
            return review_response(schema, messages, accepted=accepted, repair_scope='meanings',
                reason='Independent judgment of the entire corrected source-bound union.')
    verdict = review_current_selection(Reviewer(), source, draft.model_dump(mode='json')['decisions'],
        'Independently review the full source.', reading, attempt=2,
        meaning_revision_base=selection.model_dump(mode='json')['decisions'],
        inventory_revision_base=None, binding_budget={'used': False}, meaning_resolution=ledger)
    assert verdict.accepted is accepted
    assert not reading.audience_selection and reading.audience_part_ids is None
