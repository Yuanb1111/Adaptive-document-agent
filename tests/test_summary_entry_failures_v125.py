"""Source selection metadata and literal blank lines cannot block valid reading."""
from copy import deepcopy
from threading import Event

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.company_introduction import IntroductionPages
from adaptive_document_agent.agent.summary_reader import _read_batch
from adaptive_document_agent.agent.summary_read_binding import bind_reading, reconcile_layout
from adaptive_document_agent.agent.summary_reader import SummaryReadBatch
from adaptive_document_agent.services.summary_source import summary_scope
from tests.test_summary_line_recovery_v114 import fixture, Responses, assert_complete


def test_routing_reason_is_preserved_without_applying_a_slide_copy_limit():
    result, _, _, _ = fixture()
    reason = 'The source contains an introductory overview with qualifications. ' * 30
    selection = IntroductionPages.model_validate({'pages': [1], 'summary_ranges': [
        dict(start_page=1, end_page=1, reason=reason)]})
    assert selection.summary_ranges[0].reason == reason
    assert summary_scope(result, selection.summary_ranges) == [1]
    selection.summary_ranges[0].end_page = 2
    with pytest.raises(ValueError, match='invalid page range'):
        summary_scope(result, selection.summary_ranges)
    with pytest.raises(ValidationError):
        IntroductionPages.model_validate({'summary_ranges': [dict(start_page=1, end_page=1, reason='')]})


@pytest.mark.parametrize('role', ['content', 'heading'])
def test_model_assigned_whitespace_keeps_raw_lines_without_a_fact_or_retry(role):
    result, blocks, rows, part = fixture()
    rows.append(part(2, 2, role))
    before = deepcopy(rows)
    gateway = Responses([rows])
    outcome = _read_batch(gateway, result, blocks, Event())
    assert_complete(result, blocks, outcome)
    assert len(gateway.calls) == 1
    blank = next(p for p in outcome.parts if p.start_line == 2)
    assert blank.role == 'layout' and blank.source_text == '\n' and not blank.facts
    attempt = outcome.audit['attempts'][0]
    assert attempt['response']['parts'] == SummaryReadBatch(parts=before).model_dump()['parts']
    assert any(a['action'] == 'classify_blank_lines' and a['original_role'] == role
               for a in attempt['layout_reconciliation'])


def test_whitespace_reconciliation_does_not_reclassify_content_or_erase_facts():
    result, blocks, rows, part = fixture()
    rows.append(part(2, 2, 'content', 'An invented statement.', 2))
    bound, errors = bind_reading(SummaryReadBatch(parts=rows), blocks, result, {})
    assert errors  # Whitespace cannot support the invented fact.
    content = next(p for p in bound if p.start_line == 3)
    without_facts = content.model_copy(update={'facts': []})
    restored = reconcile_layout([without_facts], blocks, {})
    assert next(p for p in restored if p.id == content.id).role == 'content'
    # A tampered nonblank source must remain a validation failure as well.
    tampered = without_facts.model_copy(update={'start_line': 2, 'end_line': 2})
    assert reconcile_layout([tampered], blocks, {})[0].role == 'content'


def test_repeated_boundary_ownership_preserves_both_topics_and_all_fact_quotes():
    from adaptive_document_agent.agent.summary_span_ownership import reconcile_contained_spans
    result, blocks, _, part = fixture()
    rows = [part(3, 5, 'content', 'Cedar builds scheduling software for manufacturing teams.', 3),
            part(5, 5, 'content', 'Delivery requires customer training.', 5)]
    response = SummaryReadBatch(parts=rows)
    record = {}
    fixed = reconcile_contained_spans(response, blocks, record)
    assert [(p.start_line, p.end_line) for p in fixed.parts] == [(3, 4), (5, 5)]
    assert [p.facts for p in fixed.parts] == [p.facts for p in response.parts]
    assert response.parts[0].end_line == 5
    assert record['source_ownership_reconciliation'][0]['original_part']['end_line'] == 5


@pytest.mark.parametrize('change', ['crossing_quote', 'interior', 'identical', 'empty_facts', 'outside'])
def test_substantive_overlap_is_not_trimmed_without_complete_quote_ownership(change):
    from adaptive_document_agent.agent.summary_span_ownership import reconcile_contained_spans
    _, blocks, _, part = fixture()
    rows = [part(3, 5, 'content', 'Cedar builds scheduling software.', 3),
            part(5, 5, 'content', 'Delivery requires training.', 5)]
    if change == 'crossing_quote': rows[0]['facts'][0]['quote_end_line'] = 5
    if change == 'interior': rows[0]['end_line'] = 7
    if change == 'identical': rows[1]['start_line'] = 3
    if change == 'empty_facts': rows[0]['facts'] = []
    if change == 'outside': rows[0]['end_line'] = rows[1]['end_line'] = 99
    response = SummaryReadBatch(parts=rows)
    assert reconcile_contained_spans(response, blocks, {}) == response
