"""Source quote addresses preserve complete pages without trusting fabricated copy."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.source_check_references import source_quote_blocks, expand_source_quotes
from adaptive_document_agent.agent.source_coverage import check_source_scope
from tests.test_source_coverage import sample, target, gateway


def test_full_pages_round_trip_without_losing_whitespace_or_qualifications():
    source = {37: '  First line.\n\n' + 'Source conditions and numbers 12.34.\n' * 170,
              39: 'a' * 2101 + '\n  End.  '}
    original = deepcopy(source)
    blocks = source_quote_blocks(source)
    for page, text in source.items():
        assert ''.join(q['text'] for q in blocks.values() if q['page'] == page) == text
    assert all(0 < len(q['text']) <= 1000 for q in blocks.values())
    assert source == original


def test_reference_request_contains_complete_source_and_persists_literal_evidence():
    doc, ranges = sample()
    before = doc.model_dump()
    gw = gateway([dict(targets=[target()], rationale='Read conditions'),
        dict(found=True, finding='Condition applies', quotes=[dict(ref='p5_q1')])])
    revised, ledger = check_source_scope(doc, ranges, gw)
    check = ledger.checks[0]
    assert check.status == 'checked_found' and len(revised) == 2
    assert check.evidence_quotes == {5: [doc.pages[4].text]}
    assert check.attempts[0]['reference_response']['quotes'] == [dict(ref='p5_q1')]
    assert check.attempts[0]['response']['quotes'] == [dict(page=5, text=doc.pages[4].text)]
    assert doc.model_dump() == before and ledger.calls_used == 2
    message = str(gw.client.calls[-1])
    assert 'source_quote_blocks' in message and 'p6_q1' in message


def test_ellipsis_failure_is_corrected_with_owned_blocks_in_existing_second_read():
    doc, ranges = sample()
    gw = gateway([dict(targets=[target()], rationale='Check'),
        dict(found=True, finding='Condition', quotes=[dict(page=5, text='Page 5 ... condition at 5.')]),
        dict(found=True, finding='Condition', quotes=[dict(ref='p5_q1')])])
    _, ledger = check_source_scope(doc, ranges, gw)
    assert [a['status'] for a in ledger.checks[0].attempts] == ['invalid_evidence', 'accepted']
    assert ledger.calls_used == 3 and ledger.checks[0].status == 'checked_found'


@pytest.mark.parametrize('bad', ['p7_q1', 'p5_q999'])
def test_unowned_or_unknown_quote_references_fail_closed_without_extra_reads(bad):
    doc, ranges = sample()
    reply = dict(found=True, finding='Condition', quotes=[dict(ref=bad)])
    gw = gateway([dict(targets=[target()], rationale='Check'), reply, reply])
    revised, ledger = check_source_scope(doc, ranges, gw)
    check = ledger.checks[0]
    assert revised == ranges and check.status == 'failed' and not check.evidence_quotes
    assert 'Unknown source quote reference' in check.finding and ledger.calls_used == 3


def test_blank_source_span_cannot_support_a_found_finding():
    doc, ranges = sample()
    doc.pages[4].text = ' ' * 1000 + 'Actual source condition.'
    reply = dict(found=True, finding='Condition', quotes=[dict(ref='p5_q1')])
    _, ledger = check_source_scope(doc, ranges, gateway([
        dict(targets=[target()], rationale='Check'), reply, reply]))
    assert ledger.checks[0].status == 'failed' and not ledger.checks[0].evidence_quotes


def test_reference_transport_retains_format_repair_without_semantic_rewrite():
    doc, ranges = sample()
    reply = dict(found=True, finding='Condition applies', quotes=[dict(ref='p5_q1')])
    malformed = json.dumps(reply)[:-1]
    gw = gateway([dict(targets=[target()], rationale='Check'), malformed, reply])
    _, ledger = check_source_scope(doc, ranges, gw)
    assert ledger.checks[0].status == 'checked_found' and ledger.calls_used == 3
    assert ledger.checks[0].attempts[0]['format_repair']


def test_expansion_does_not_modify_model_response_or_promote_legacy_literal_quotes():
    value = dict(found=True, finding='Condition', quotes=[dict(page=99, text='Invented')])
    assert expand_source_quotes(value, {'p5_q1': dict(page=5, text='Actual source')}) == value
    referenced = dict(quotes=[dict(ref='p5_q1')])
    original = deepcopy(referenced)
    expanded = expand_source_quotes(referenced, {'p5_q1': dict(page=5, text='Actual source')})
    assert expanded['quotes'][0] == dict(page=5, text='Actual source') and referenced == original
