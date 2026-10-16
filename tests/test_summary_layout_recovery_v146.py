"""Source geometry proves layout; semantic recovery remains a bounded model decision."""
from copy import deepcopy
from threading import Event

import pytest

from adaptive_document_agent.agent.summary_reader import _read_batch
from adaptive_document_agent.models.summary import SummaryReview
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from adaptive_document_agent.services.summary_layout_evidence import mechanical_layout, layout_line_evidence
from adaptive_document_agent.services.summary_source import source_blocks
from adaptive_document_agent.services.summary_validation import reading_errors
from tests.test_complete_summary_reading import source
from tests.test_summary_line_recovery_v114 import Responses


def _geometry(text, top, bottom=None):
    return {'text': text, 'bbox': [40, top, 400, bottom or top + 12]}


def rotated_source(labels=('OPERATING MODEL',)):
    result = source(2)
    for page in result.document.pages:
        body, footer = 'Reported values by channel', f'– {page.page_number} –'
        page.text = '\n'.join((body, *labels, footer)) + '\n'
        page.raw_text = '\n'.join((*labels, body, footer))
        page.reading_rotation = 90
        page.text_blocks = [{'lines': [_geometry(label, 30 + i * 18) for i, label in enumerate(labels)]
                                      + [_geometry(body, 120, 500), _geometry(footer, 800)]}]
    return result


@pytest.mark.parametrize('labels', [('OPERATING MODEL',), ('Research Report', 'Study Methods'), ('研究报告', '方法概述')])
def test_rotated_grouped_headers_and_page_marker_use_retained_geometry(labels):
    result = rotated_source(labels)
    before = result.document.model_dump(mode='json')
    for page in result.document.pages:
        grouped = '\n'.join(page.text.splitlines()[1:])
        proof = layout_line_evidence(grouped, page.page_number, result)
        assert mechanical_layout(grouped, page.page_number, result)
        assert [row['basis'] for row in proof] == ['repeated_source_margin'] * len(labels) + ['literal_terminal_page_marker']
        assert all(row['peer_pages'] == [1, 2] for row in proof[:-1])
    assert result.document.model_dump(mode='json') == before


def test_source_geometry_overrides_misleading_first_line_of_extracted_text():
    result = rotated_source()
    for page in result.document.pages:
        page.text = 'Financial Outlook\nOPERATING MODEL\n– 1 –'
        page.text_blocks[0]['lines'].insert(1, _geometry('Financial Outlook', 300))
    assert not mechanical_layout('Financial Outlook', 1, result)


def test_length_does_not_overrule_individually_proved_header_lines():
    labels = ('Cross Regional Operational Implementation And Manufacturing Coordination Review Reference Catalogue',
              'International Research Methodology And Consolidated Performance Reporting Framework Reference')
    result = rotated_source(labels)
    grouped = '\n'.join(result.document.pages[0].text.splitlines()[1:])
    assert len(' '.join(grouped.split())) > 180
    assert mechanical_layout(grouped, 1, result)


@pytest.mark.parametrize('disclaimer', ['No dividends were declared.',
    'NO DIVIDENDS WERE DECLARED.',
    'Do not rely on the forecasts in this document.',
    'No dividends were declared and future distributions remain subject to approval'])
@pytest.mark.parametrize('geometry', [False, True])
def test_repeated_edge_disclaimer_cannot_be_hidden_as_layout(disclaimer, geometry):
    result = source(2)
    for page in result.document.pages:
        page.text = disclaimer + '\nA separate body passage.\n– 1 –'
        if geometry:
            page.text_blocks = [{'lines': [_geometry(disclaimer, 30),
                _geometry('A separate body passage.', 150), _geometry('– 1 –', 800)]}]
    assert not mechanical_layout(disclaimer, 1, result)


def test_one_proved_footer_cannot_lend_layout_proof_to_adjacent_cross_reference():
    result = rotated_source()
    page = result.document.pages[0]
    sentence = 'For further details, see “Services — Delivery”.'
    page.text = f'OPERATING MODEL\n{sentence}\n– 1 –'
    proof = layout_line_evidence(sentence + '\n– 1 –', 1, result)
    assert [line['proved'] for line in proof] == [False, True]
    assert not mechanical_layout(sentence + '\n– 1 –', 1, result)


def test_matching_heading_in_body_leaves_geometry_ownership_ambiguous():
    result = rotated_source()
    result.document.pages[0].text_blocks[0]['lines'].append(_geometry('OPERATING MODEL', 300))
    assert not mechanical_layout('OPERATING MODEL', 1, result)


def test_numeric_table_body_cannot_become_layout_because_a_year_is_present():
    result = source(1)
    result.document.pages[0].text = 'Year ended 2023 2024\n100 200 300\n– 1 –'
    assert mechanical_layout('Year ended 2023 2024', 1, result)
    assert not mechanical_layout('2023 2024\n100 200 300', 1, result)


def repair_source(include_long_note=False):
    result = source(1)
    sentence = 'For further details, see “Services — Delivery”.'
    note = 'The map illustrates our operating locations and does not imply service availability. ' * 3
    lines = ['SUMMARY', 'Cedar provides scheduling software.']
    if include_long_note:
        lines.append(note)
    lines += [sentence, '– 1 –']
    result.document.pages[0].text = '\n'.join(lines)
    blocks = source_blocks(result, [1])
    def row(start, end, role, fact=''):
        return dict(block_id=blocks[0].id, start_line=start, end_line=end, role=role,
            title='Source passage', reading_note='Read the literal source passage.',
            facts=[dict(label='Operations', text=fact, quote_start_line=start, quote_end_line=end)] if fact else [])
    rows = [row(1, 1, 'heading'), row(2, 2, 'content', lines[1])]
    if include_long_note:
        rows.append(row(3, 3, 'layout'))
    crossref = len(lines) - 1
    rows.append(row(crossref, len(lines), 'layout'))
    return result, blocks, rows, row


def test_short_layout_retry_needs_model_content_decision_and_preserves_literal_cross_reference():
    result, blocks, rows, row = repair_source()
    before = deepcopy(rows)
    client = Responses([rows, rows, [rows[-1]], [row(3, 3, 'content'), row(4, 4, 'layout')]])
    outcome = _read_batch(client, result, blocks, Event())
    assert outcome.error is None and len(client.calls) == 4
    review = SummaryReview(document_id=result.document.document_id, document_sha256=result.document.sha256,
        source_pages=[1], source_blocks=blocks, parts=outcome.parts)
    assert not reading_errors(review, result)
    assert rows == before
    crossref = next(part for part in outcome.parts if part.start_line == 3)
    assert crossref.role == 'content' and crossref.facts[0].evidence_only
    assert crossref.facts[0].text == crossref.facts[0].source_quote == result.document.pages[0].text.splitlines()[2]
    audit = outcome.audit['rejected_part_read']
    assert [line['proved'] for line in audit['layout_evidence'][0]['lines']] == [False, True]
    assert audit['errors'] == [] and audit['layout_retry']['previous_errors']
    assert audit['layout_retry']['errors'] == []
    assert next(part for part in outcome.parts if part.start_line == 2).facts[0].text == rows[1]['facts'][0]['text']
    assert 'source cross-references' in client.calls[-1][-1]['content']


def test_terminal_error_reports_current_unproved_layout_and_keeps_prior_rejections():
    result, blocks, rows, row = repair_source(include_long_note=True)
    first_target = [row(3, 3, 'content'), rows[-1]]
    client = Responses([rows, rows, first_target, [rows[-1]]])
    outcome = _read_batch(client, result, blocks, Event())
    assert outcome.error and not outcome.parts and len(client.calls) == 4
    assert 'Layout-only classification cannot hide' not in str(outcome.error)
    assert 'Layout-only classification cannot hide' in outcome.audit['attempts'][1]['errors'][0]
    assert outcome.audit['rejected_part_read']['layout_retry']['previous_errors']


def test_layout_retry_privacy_failure_is_preserved_without_further_attempt():
    result, blocks, rows, _ = repair_source()
    failure = PrivacyViolationError('Local Only')
    client = Responses([rows, rows, [rows[-1]], failure])
    outcome = _read_batch(client, result, blocks, Event())
    assert outcome.error is failure and not outcome.parts and len(client.calls) == 4
    audit = outcome.audit['rejected_part_read']
    assert audit['error'] == 'Local Only' and audit['errors'] == ['Local Only']
    assert audit['layout_retry']['previous_errors']
