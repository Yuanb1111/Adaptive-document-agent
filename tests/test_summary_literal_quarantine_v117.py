"""Internal recovery retains evidence; it never certifies rejected model claims."""
from copy import deepcopy
from threading import Event

import pytest

from adaptive_document_agent.agent.company_introduction import IntroductionDraft
from adaptive_document_agent.agent.summary_reader import _read_batch
from adaptive_document_agent.agent.summary_reading_layout import reading_presentation
from adaptive_document_agent.services.source_quotes import normalize_quote
from adaptive_document_agent.services.summary_source import source_blocks
from adaptive_document_agent.services.summary_validation import reading_errors
from tests.test_summary_line_recovery_v114 import Responses, assert_complete, fixture
from tests.test_summary_semantic_recovery_v115 import diagram_fixture


@pytest.mark.parametrize('note', ['The table reports 83.6%.', 'Revenue was USD 999 million in 2099.'])
def test_repeated_invalid_annotations_are_audited_not_promoted_to_evidence(note):
    result, blocks, rows, _ = fixture()
    rows[1].update(title='Performance in 2099', reading_note=note)
    original = deepcopy(rows)
    outcome = _read_batch(Responses([rows,rows]),result,blocks,Event())
    review = assert_complete(result,blocks,outcome)
    assert rows == original
    part = next(p for p in review.parts if p.start_line == 3)
    assert part.title == 'Source passage' and '2099' not in part.reading_note
    assert part.facts[0].text == rows[1]['facts'][0]['text']
    audit = outcome.audit['attempts'][1]['quarantined_annotations'][0]
    assert audit['reading_note'] == note and audit['title'] == original[1]['title']
    part.facts[0].text = 'Revenue was USD 999 million in 2099.'
    assert reading_errors(review,result)


def test_long_exact_quote_preserves_all_words_pages_and_qualifications():
    result, _, _, make = fixture()
    source = 'Products include software and controllers for warehouse operators.\n' * 110
    source += 'Delivery is conditional on customer integration and staff training.'
    result.document.pages[0].text = 'SUMMARY\n' + source
    blocks = source_blocks(result,[1])
    end = len(result.document.pages[0].text.splitlines())
    rows = [make(1,1,'heading'),make(2,end,'content','An unverified description of the products.',2)]
    for row in rows: row['block_id'] = blocks[0].id
    rows[1]['facts'][0]['quote_end_line'] = end
    outcome = _read_batch(Responses([rows]),result,blocks,Event())
    review = assert_complete(result,blocks,outcome)
    facts = review.parts[1].facts
    assert len(facts) > 1 and all(f.evidence_only and f.source_pages == [1] for f in facts)
    assert normalize_quote(' '.join(f.source_quote for f in facts)) == normalize_quote(source)
    assert all(len(f.source_quote) <= 6000 and f.text == f.source_quote for f in facts)
    assert 'staff training' in facts[-1].text
    assert outcome.audit['attempts'][0]['long_literal_quotes'][0]['model_fact'] == rows[1]['facts'][0]
    with pytest.raises(ValueError,match='model-authored editorial'):
        reading_presentation(review,result,IntroductionDraft)


@pytest.mark.parametrize('bad', ['invention','cross_part_quote'])
def test_targeted_repair_quarantines_claim_and_keeps_only_entire_owned_source(bad):
    result, blocks, rows, fixes = diagram_fixture()
    fixes = fixes[:1]
    if bad == 'invention':
        fixes[0]['facts'][0]['text'] = 'There are 999 devices.'
    else:
        fixes[0]['facts'][0]['quote_start_line'] = 2
    outcome = _read_batch(Responses([rows,rows,fixes]),result,blocks,Event())
    review = assert_complete(result,blocks,outcome)
    fact = review.parts[2].facts[0]
    assert fact.evidence_only and fact.text == fact.source_quote == blocks[0].text.splitlines()[2]
    assert '999' not in fact.text and 'Cedar makes' not in fact.source_quote
    record = outcome.audit['rejected_part_read']
    assert record['response']['parts'] == fixes
    assert record.get('literal_extracts') or record.get('quarantined_cross_part_facts')
    with pytest.raises(ValueError,match='model-authored editorial'):
        reading_presentation(review,result,IntroductionDraft)


@pytest.mark.parametrize('role,end,fact', [('layout',8,False),('content',8,False),('layout',9,False),('layout',8,True)])
def test_only_one_past_end_fact_free_layout_can_be_reconciled(role,end,fact):
    result, blocks, rows, make = fixture()
    rows[2]['end_line'] = 5
    rows[-1] = make(7,end,role,'Unverified footer text.' if fact else '',7 if fact else None)
    outcome = _read_batch(Responses([rows,rows]),result,blocks,Event())
    if role == 'layout' and end == 8 and not fact:
        assert_complete(result,blocks,outcome)
        assert outcome.audit['attempts'][1]['layout_endpoints'][0]['original_end_line'] == 8
        assert next(p for p in outcome.parts if p.start_line == 7).source_text == '-- i --'
    else:
        assert outcome.error
