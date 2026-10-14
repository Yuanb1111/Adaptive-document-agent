"""Page layout and literal evidence must not manufacture reading failures."""
from copy import deepcopy
from threading import Event

import pytest

from adaptive_document_agent.agent.summary_reader import _read_batch
from adaptive_document_agent.agent.summary_reading_layout import reading_presentation
from adaptive_document_agent.agent.company_introduction import IntroductionDraft
from adaptive_document_agent.services.summary_source import source_blocks, reading_batches
from adaptive_document_agent.services.summary_validation import reading_errors, presentation_errors
from tests.test_summary_line_recovery_v114 import Responses, fixture, assert_complete


def test_page_fitting_request_keeps_table_headers_and_wrapped_sentence_together():
    result, _, _, _ = fixture()
    text = 'SUMMARY\n' + ('Context sentence.\n' * 370) + 'Year ended 2024\n(RMB in thousands)\nRevenue 300\n'
    text += 'Approximately 35.0% of proceeds will be used\nfor expanding the disclosed services.\n'
    assert 6500 < len(text) < 12000
    result.document.pages[0].text = text
    blocks = source_blocks(result,[1])
    assert len(blocks) == 1 and blocks[0].text == text
    assert blocks[0].char_start == 0 and blocks[0].char_end == len(text)
    assert reading_batches(blocks) == [blocks]


def test_oversized_page_remains_lossless_and_bounded():
    result, _, _, _ = fixture()
    text = 'SUMMARY\n' + 'A disclosed source sentence.\n' * 1500
    result.document.pages[0].text = text
    blocks = source_blocks(result,[1])
    assert len(blocks) > 1 and ''.join(b.text for b in blocks) == text
    assert all(sum(len(b.text) for b in batch) <= 12000 for batch in reading_batches(blocks))
    assert all(a.char_end == b.char_start for a,b in zip(blocks,blocks[1:]))


@pytest.mark.parametrize('substantive', [False, True])
def test_alignment_spaces_do_not_make_header_substantive_or_hide_body(substantive):
    result, _, _, make = fixture()
    body = ('Warehouse architecture includes software, controllers and monitoring. ' * 5
            if substantive else 'Year ended December 31,\n' + ' ' * 250 + '2023    2024    2025\n' +
            ' ' * 250 + '(RMB in thousands)')
    result.document.pages[0].text = 'SUMMARY\n' + body
    blocks = source_blocks(result,[1])
    row = make(1 if substantive else 2,len(result.document.pages[0].text.splitlines()),'layout')
    row['block_id'] = blocks[0].id
    heading = make(1,1,'heading'); heading['block_id'] = blocks[0].id
    rows = [row] if substantive else [heading,row]
    outcome = _read_batch(Responses([rows,rows,rows]),result,blocks,Event())
    if substantive:
        assert outcome.error and 'substantive source passage' in str(outcome.error)
    else:
        assert_complete(result,blocks,outcome)
        assert len(outcome.audit['attempts']) == 1
        assert ''.join(p.source_text for p in outcome.parts) == result.document.pages[0].text


def test_model_assigned_unparaphrased_content_retains_evidence_and_requires_editor():
    result, blocks, rows, _ = fixture()
    rows[1]['facts'] = []
    before = deepcopy(rows)
    outcome = _read_batch(Responses([rows,rows]),result,blocks,Event())
    review = assert_complete(result,blocks,outcome)
    fact = next(p.facts[0] for p in review.parts if p.start_line==3)
    assert fact.evidence_only and fact.text == fact.source_quote == blocks[0].text.splitlines()[2]
    assert rows == before and outcome.audit['attempts'][1]['literal_passages']
    with pytest.raises(ValueError,match='model-authored editorial'):
        reading_presentation(review,result,IntroductionDraft)


def test_rejected_paraphrase_cannot_leave_unsupported_period_in_label():
    result, blocks, rows, _ = fixture()
    rows[1]['facts'][0].update(label='Revenue in 2099',text='Revenue was USD 999 million in 2099.')
    outcome = _read_batch(Responses([rows,rows]),result,blocks,Event())
    assert_complete(result,blocks,outcome)
    fact = next(p.facts[0] for p in outcome.parts if p.start_line==3)
    assert fact.text == fact.source_quote and '2099' not in fact.label
    assert outcome.audit['attempts'][1]['literal_extracts'][0]['rejected_label'] == 'Revenue in 2099'


def test_literal_evidence_flag_cannot_disguise_unsupported_numbers():
    result, blocks, rows, _ = fixture()
    outcome = _read_batch(Responses([rows]),result,blocks,Event())
    review = assert_complete(result,blocks,outcome)
    fact = next(p.facts[0] for p in review.parts if p.role=='content')
    fact.evidence_only = True
    fact.text = 'Cedar supplies 999 machines.'
    assert reading_errors(review,result)


def test_export_validator_rejects_literal_evidence_as_unedited_slide_copy():
    from tests.test_complete_summary_reading import generate
    result = generate()
    company = result.presentation_plan.company
    first = company.summary_pages[0].items[0]
    first.evidence_only = True
    assert any('model-authored editorial' in e for e in presentation_errors(
        company.summary_review,company.summary_pages,result))
