"""Report retries complete saved source reads without changing extraction scope."""
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.source_coverage import check_source_scope, retry_failed_source_checks
from tests.test_source_coverage import sample, gateway, target


def _failed():
    doc, ranges = sample()
    bad = dict(found=True, finding='Condition', quotes=[dict(page=5, text='Invented')])
    _, ledger = check_source_scope(doc, ranges, gateway([
        dict(targets=[target()], rationale='Check'), bad, bad]))
    return doc, SimpleNamespace(source_coverage=ledger, analysis_page_ranges=ranges)


def test_report_retry_preserves_history_and_raw_scope_then_skips_completed_read():
    doc, profile = _failed()
    before = doc.model_dump(), list(profile.analysis_page_ranges)
    check = profile.source_coverage.checks[0]
    history = [dict(a) for a in check.attempts]
    gw = gateway([dict(found=True, finding='Condition applies',
                       quotes=[dict(page=5, text='Literal source condition at 5.')])])
    retry_failed_source_checks(doc, profile, gw)
    assert check.status == 'checked_found'
    assert check.attempts[:2] == history
    assert check.evidence_quotes == {5: ['Literal source condition at 5.']}
    assert profile.source_coverage.calls_used == 4
    assert profile.source_coverage.max_calls == 10
    assert (doc.model_dump(), profile.analysis_page_ranges) == before
    retry_failed_source_checks(doc, profile, gw)
    assert len(gw.client.calls) == 1


def test_failed_retry_remains_failed_and_does_not_invent_absence():
    doc, profile = _failed()
    bad = dict(found=True, finding='Condition', quotes=[dict(page=5, text='Invented')])
    gw = gateway([bad, bad])
    retry_failed_source_checks(doc, profile, gw)
    check = profile.source_coverage.checks[0]
    assert check.status == 'failed' and not check.evidence_quotes
    assert len(check.attempts) == 4 and len(gw.client.calls) == 2
    assert 'no absence conclusion' in check.finding


@pytest.mark.parametrize('pages', [[], [3], [5, 7], [5, 6, 7, 8]])
def test_invalid_saved_targets_are_not_expanded_or_sent(pages):
    doc, profile = _failed()
    profile.source_coverage.checks[0].pages = pages
    gw = gateway([])
    retry_failed_source_checks(doc, profile, gw)
    assert not gw.client.calls
    assert profile.source_coverage.checks[0].status == 'failed'


def test_missing_complete_page_text_remains_incomplete_without_model_call():
    doc, profile = _failed()
    doc.pages[4].text = ''
    gw = gateway([])
    retry_failed_source_checks(doc, profile, gw)
    assert profile.source_coverage.checks[0].status == 'incomplete'
    assert not gw.client.calls


def test_oversized_finding_gets_source_aware_rewrite_not_format_only_repair():
    doc, profile = _failed()
    quotes = [dict(page=5, text='Literal source condition at 5.')]
    gw = gateway([dict(found=True, finding='Source condition. ' * 100, quotes=quotes),
                  dict(found=True, finding='Source condition applies.', quotes=quotes)])
    retry_failed_source_checks(doc, profile, gw)
    check = profile.source_coverage.checks[0]
    assert check.status == 'checked_found'
    assert [a['status'] for a in check.attempts[-2:]] == ['finding_too_long', 'accepted']
    assert 'format_repair' not in check.attempts[-2]
    assert len(gw.client.calls) == 2
    assert check.evidence_quotes == {5: ['Literal source condition at 5.']}


def test_repeated_oversized_finding_remains_failed_after_two_reads():
    doc, profile = _failed()
    long = dict(found=True, finding='Source condition. ' * 100,
                quotes=[dict(page=5, text='Literal source condition at 5.')])
    gw = gateway([long, long])
    retry_failed_source_checks(doc, profile, gw)
    check = profile.source_coverage.checks[0]
    assert check.status == 'failed' and not check.evidence_quotes
    assert len(gw.client.calls) == 2
    assert all('format_repair' not in a for a in check.attempts[-2:])
