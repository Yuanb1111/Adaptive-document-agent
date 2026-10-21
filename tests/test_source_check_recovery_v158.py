"""Supplementary recovery keeps literal evidence, hard bounds and diagnostic causes."""
import pytest
from tests.test_source_coverage import sample, gateway, target
from adaptive_document_agent.agent.source_coverage import check_source_scope


def test_bad_source_quote_gets_one_scoped_recheck_and_retains_both_responses():
    doc, ranges = sample()
    gw = gateway([dict(targets=[target()], rationale='Check conditions'),
        dict(found=True, finding='Condition', quotes=[dict(page=5, text='Invented')]),
        dict(found=True, finding='Condition applies', quotes=[dict(page=5, text='Literal source condition at 5.')])])
    revised, ledger = check_source_scope(doc, ranges, gw)
    check = ledger.checks[0]
    assert len(revised) == 2 and check.status == 'checked_found'
    assert [a['status'] for a in check.attempts] == ['invalid_evidence', 'accepted']
    assert check.attempts[0]['response']['quotes'][0]['text'] == 'Invented'
    assert ledger.calls_used == len(gw.client.calls) == 3


def test_repeated_bad_quote_fails_closed_with_exact_error_and_no_third_read():
    doc, ranges = sample()
    bad = dict(found=True, finding='Condition', quotes=[dict(page=7, text='Wrong page text')])
    gw = gateway([dict(targets=[target()], rationale='Check'), bad, bad])
    revised, ledger = check_source_scope(doc, ranges, gw)
    check = ledger.checks[0]
    assert revised == ranges and check.status == 'failed' and not check.evidence_quotes
    assert len(check.attempts) == 2 and ledger.calls_used == 3
    assert 'Quotation not present' in check.attempts[-1]['validation_detail']
    assert 'no absence conclusion' in check.finding


def test_malformed_source_read_uses_content_preserving_gateway_format_repair():
    doc, ranges = sample()
    broken = '{"found":true,"finding":"Condition","quotes":[{"page":5,"text":"Literal source condition at 5."}]'
    good = broken + '}'
    gw = gateway([dict(targets=[target()], rationale='Check'), broken, good])
    revised, ledger = check_source_scope(doc, ranges, gw)
    check = ledger.checks[0]
    assert len(revised) == 2 and check.status == 'checked_found' and ledger.calls_used == 3
    assert check.attempts[0]['raw_response'] == broken
    assert check.attempts[0]['format_repair']
    assert len(gw.client.calls) == 3 and len(gw.usage) == 3


def test_two_failed_reads_with_both_repairs_stay_under_total_bound():
    doc, ranges = sample()
    # Each target: malformed JSON -> format repair -> one evidence correction.
    bad = '{"found":true,"finding":"Condition","quotes":[{"page":5,"text":"Wrong"}]'
    good_format = bad + '}'
    bad_evidence = dict(found=True, finding='Condition', quotes=[dict(page=5, text='Wrong')])
    gw = gateway([dict(targets=[target(5,5), target(7,8)], rationale='Check'),
                  bad, good_format, bad_evidence, bad, good_format, bad_evidence])
    revised, ledger = check_source_scope(doc, ranges, gw)
    assert revised == ranges and all(c.status == 'failed' for c in ledger.checks)
    assert ledger.calls_used == ledger.max_calls == len(gw.client.calls) == 7
