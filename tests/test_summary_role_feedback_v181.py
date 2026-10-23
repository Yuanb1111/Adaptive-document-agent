"""Layout errors name valid roles without deciding source meaning in Python."""
from copy import deepcopy
import json
from threading import Event

import pytest

from adaptive_document_agent.agent.summary_reader import _read_batch
from tests.test_summary_line_recovery_v114 import Responses, assert_complete
from tests.test_summary_targeted_scope_v174 import scope_fixture


def feedback(messages):
    return json.loads(messages[2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


@pytest.mark.parametrize('correct_at', [1, 2, 3])
def test_heading_label_can_be_corrected_without_discarding_accepted_substance(correct_at):
    result, blocks, rows, _, headings = scope_fixture()
    before = deepcopy((result, blocks, rows))
    corrected = headings + rows[1:] if correct_at == 1 else headings
    replies = [rows] * min(correct_at, 2)
    if correct_at == 3:
        replies.append(rows[:1])
    client = Responses(replies + [corrected])
    outcome = _read_batch(client, result, blocks, Event())
    assert_complete(result, blocks, outcome)
    assert len(client.calls) == correct_at + 1
    assert (result, blocks, rows) == before
    for messages in client.calls[1:]:
        proof = feedback(messages)['layout_evidence'][0]['lines']
        label = next(line for line in proof if line['text'].strip() == 'Notes:')
        assert label['line'] == 3 and not label['proved']
        assert label['allowed_roles'] == ['heading', 'content']
        blank = next(line for line in proof if not line['text'].strip())
        assert blank['proved'] and 'layout' in blank['allowed_roles']
        assert 'allowed_roles' in messages[-1]['content']
    label_part = next(p for p in outcome.parts if p.start_line == 3)
    assert label_part.role == 'heading' and label_part.source_text == 'Notes:\n' and not label_part.facts
    body = next(p for p in outcome.parts if p.start_line == 4)
    assert body.facts[0].text == rows[1]['facts'][0]['text']


def test_unchanged_invalid_layout_is_still_rejected_with_same_four_call_bound():
    result, blocks, rows, _, _ = scope_fixture()
    client = Responses([rows, rows, rows[:1], rows[:1]])
    outcome = _read_batch(client, result, blocks, Event())
    assert outcome.error and not outcome.parts and len(client.calls) == 4
    assert 'Nonblank layout needs' in str(outcome.error)
    assert outcome.audit['attempts'][0]['response']['parts'] == rows
    assert outcome.audit['rejected_part_read']['layout_retry']['response']['parts'] == rows[:1]
