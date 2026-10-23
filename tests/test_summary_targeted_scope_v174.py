"""A bounded scope retry never rewrites accepted reading or clips crossing facts."""
from copy import deepcopy
import json
from threading import Event

import pytest

from adaptive_document_agent.agent.summary_read_binding import bind_reading
from adaptive_document_agent.agent.summary_reader import SummaryReadBatch, _read_batch
from adaptive_document_agent.agent.summary_read_scope import targeted_source_messages
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from adaptive_document_agent.services.summary_source import source_blocks
from tests.test_complete_summary_reading import source
from tests.test_summary_line_recovery_v114 import Responses, assert_complete


def scope_fixture():
    result = source(1)
    result.document.pages[0].text = 'SUMMARY\n\nNotes:\nA service condition requires approval.\n– 1 –'
    blocks = source_blocks(result, [1])
    def part(start, end, role, fact=None):
        return dict(block_id=blocks[0].id, start_line=start, end_line=end, role=role,
            title='Source passage', reading_note='The supplied passage is retained.',
            facts=[dict(label='Service condition', text=fact, quote_start_line=4, quote_end_line=4)] if fact else [])
    accepted = part(4, 4, 'content', 'A service condition requires approval.')
    rows = [part(1, 3, 'layout'), accepted, part(5, 5, 'layout')]
    crossing = [part(1, 2, 'layout'), part(3, 4, 'content', 'A service condition requires approval.')]
    corrected = [part(1, 1, 'heading'), part(2, 2, 'layout'), part(3, 3, 'heading')]
    return result, blocks, rows, crossing, corrected


def test_boundary_recovery_uses_only_requested_lines_and_keeps_accepted_facts_exactly():
    result, blocks, rows, crossing, corrected = scope_fixture()
    before = deepcopy(rows)
    client = Responses([rows, rows, crossing, corrected])
    outcome = _read_batch(client, result, blocks, Event())
    assert_complete(result, blocks, outcome)
    assert len(client.calls) == 4 and rows == before
    accepted, _ = bind_reading(SummaryReadBatch(parts=rows), blocks, result, {}, literal_fallback=True)
    assert [p for p in outcome.parts if p.start_line >= 4] == [p for p in accepted if p.start_line >= 4]
    for request in client.calls[2:]:
        payload = json.loads(request[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        assert [line[0] for line in payload[0]['lines']] == [1, 2, 3]
        assert 'A service condition requires approval.' not in request[1]['content']
        assert 'ORIGINAL line numbers' in request[-1]['content']
    audit = outcome.audit['rejected_part_read']
    assert audit['response']['parts'] == crossing
    assert audit['scope_retry']['response']['parts'] == corrected
    assert audit['scope_retry']['ranges'] == audit['ranges']
    assert audit['scope_retry']['scope_violations']
    assert audit['errors'] == []


@pytest.mark.parametrize('last', ['crossing', 'privacy', 'substance_as_layout'])
def test_scope_retry_is_bounded_and_never_overrides_remaining_validation(last):
    result, blocks, rows, crossing, _ = scope_fixture()
    final = crossing if last == 'crossing' else PrivacyViolationError('Local Only') if last == 'privacy' else rows[:1]
    client = Responses([rows, rows, crossing, final])
    outcome = _read_batch(client, result, blocks, Event())
    assert outcome.error is not None and not outcome.parts and len(client.calls) == 4
    if last == 'privacy':
        assert outcome.error is final
    assert outcome.audit['rejected_part_read']['scope_retry']['previous_errors']


@pytest.mark.parametrize('change', ['unknown_block', 'outside_block'])
def test_unknown_source_or_out_of_block_endpoint_cannot_get_an_ownership_retry(change):
    result, blocks, rows, crossing, _ = scope_fixture()
    if change == 'unknown_block':
        crossing[-1]['block_id'] = 'not-a-source-block'
    else:
        crossing[-1]['end_line'] = 999
    client = Responses([rows, rows, crossing])
    outcome = _read_batch(client, result, blocks, Event())
    assert outcome.error is not None and not outcome.parts and len(client.calls) == 3
    assert 'scope_retry' not in outcome.audit['rejected_part_read']


def test_disjoint_excerpt_requests_preserve_original_line_numbers_and_all_selected_text():
    _, blocks, _, _, _ = scope_fixture()
    ranges = [dict(block_id=blocks[0].id, start_line=n, end_line=n) for n in (2, 5)]
    messages = targeted_source_messages([{'role': 'system', 'content': 'Read supplied evidence.'},
                                        {'role': 'user', 'content': 'Old full source'}], blocks, ranges)
    payload = json.loads(messages[1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert payload[0]['lines'] == [[2, '\n'], [5, '– 1 –']]
    assert payload[0]['allowed_ranges'] == [dict(start_line=n, end_line=n) for n in (2, 5)]
    assert 'Old full source' not in str(messages)
