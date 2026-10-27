"""Invalid meaning references consume the existing bounded protocol correction."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_audience_review import IntroductionAudienceReview
from adaptive_document_agent.agent.introduction_meaning_resolution import resolve_meaning_findings
from adaptive_document_agent.agent.introduction_resolution_feedback import MeaningReferenceError
from tests.test_introduction_meaning_resolution_v147 import resolution_fixture
from tests.test_introduction_resolution_feedback_v181 import Replies, fixture, resolve


@pytest.mark.parametrize('fault', ['unknown', 'duplicate', 'foreign'])
@pytest.mark.parametrize('repeated', [False, True])
def test_reference_feedback_preserves_ownership_and_stops_after_one_correction(fault, repeated):
    _, reading, source, selection, findings, valid = resolution_fixture()
    selection.decisions[1].include = True
    selection.decisions[1].required_meanings = [selection.decisions[0].required_meanings[0].model_copy(deep=True)]
    invalid = valid.model_copy(deep=True)
    invalid.finding_dispositions[0].referenced_meaning_ids = {
        'unknown': ['unknown'], 'duplicate': ['part-0:meaning-2'] * 2,
        'foreign': ['part-1:meaning-1']}[fault]
    verdict = IntroductionAudienceReview(accepted=False, reason='Review the exact assertion.',
        repair_scope='meanings', findings=[{k:v for k,v in row.items() if k != 'finding_id'} for row in findings])
    client = Replies(invalid, invalid if repeated else valid)
    before = deepcopy((source, selection))
    args = (client, source, selection, selection.model_dump(mode='json')['decisions'], verdict, reading)
    if repeated:
        with pytest.raises(MeaningReferenceError):
            resolve_meaning_findings(*args)
    else:
        draft, ledger = resolve_meaning_findings(*args)
        assert draft == selection
        assert ledger['semantic_approval'] is False
    assert len(client.messages) == 2
    assert client.messages[1][:2] == client.messages[0]
    feedback = json.loads(client.messages[1][2]['content'].split('\n',1)[1].rsplit('\n',1)[0])['reference_error']
    assert feedback['received_references'] == invalid.finding_dispositions[0].referenced_meaning_ids
    assert feedback['allowed_current_meaning_ids'] == [f'part-0:meaning-{n}' for n in range(1,4)]
    assert feedback['part_id'] == 'part-0'
    assert (source, selection) == before
    assert not reading.audience_selection


def test_reference_and_unapplied_errors_share_one_protocol_correction():
    values = fixture()
    invalid = values[4].model_copy(deep=True)
    invalid.finding_dispositions[0].referenced_meaning_ids = ['unknown']
    client = Replies(invalid, values[4])
    with pytest.raises(ValueError, match='Corrected disposition needs'):
        resolve(client, values)
    assert len(client.messages) == 2
