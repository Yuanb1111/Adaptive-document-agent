"""Assurance feedback must retain the table and measure, with fresh review."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_audit_scope import (
    audit_status_errors, audit_status_options, source_audit_scope,
)
from adaptive_document_agent.agent.brief_semantic_repair import correct_new_meaning_errors
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_brief_audit_scope_v146 import _case
from tests.test_brief_targeted_contract_v147 import Replies


def mixed_tables():
    result, brief = _case()
    fees = result.document.pages[0]
    fee_table = fees.tables[0]
    fee_table.headers = ['label', 'Amount', 'Amount']
    fee_table.raw_header_lines.append('Amount Amount')
    fees.text = '\n'.join(fee_table.raw_header_lines) + '\nProgramme fees . . . 1,250 1,475'
    brief.items[0].evidence[0].text = fees.text
    prices = fees.model_copy(deep=True)
    prices.page_number = 2
    price_table = prices.tables[0]
    price_table.table_id, price_table.page = 'unit-prices', 2
    price_table.headers = ['label', 'Unit price', 'Unit price']
    price_table.column_audit_statuses = ['unknown'] * 3
    price_table.rows[0].cells = ['Programme prices', '6', '7']
    price_table.rows[0].page = 2
    price_table.raw_header_lines = ['Six months ended June 30,', '2023 2024',
        'Unit price Unit price', '(USD in thousands/unit)']
    prices.text = '\n'.join(price_table.raw_header_lines) + '\nProgramme prices . . . 6 7'
    prices.text_blocks[0]['lines'] = [line for line in prices.text_blocks[0]['lines']
                                    if 'unaudited' not in line['text']]
    result.document.pages.append(prices)
    brief.items[0].evidence.append(brief.items[0].evidence[0].model_copy(
        update={'page': 2, 'text': prices.text}))
    brief.items[0].text = ('Programme fees were USD1,250 thousand in 6M2023. '
                          'Programme prices were USD6 thousand per unit in 6M2023.')
    return result, brief


def test_same_period_unknown_in_another_table_does_not_erase_known_measure_status():
    result, brief = mixed_tables()
    before = result.model_dump_json()
    options = audit_status_options(brief.items[0], result)
    comparative = [row for row in options if row['period'] == '6M2023']
    assert [(row['source_page'], row['source_table_id'], row['status']) for row in comparative] == [
        (1, 'fees', 'unaudited'), (2, 'unit-prices', 'unknown')]
    assert comparative[0]['source_column_label'] == 'amount'
    assert comparative[1]['source_column_label'] == 'unit price'
    assert comparative[0]['source_row_labels'] == ['Programme fees']
    assert comparative[1]['source_row_labels'] == ['Programme prices']
    assert comparative[0]['allowed_spellings'] == ['6M2023 (unaudited)', 'unaudited 6M2023']
    assert comparative[1]['allowed_spellings'] == []
    assert all(row['date_aliases'] == ['2023-06-30'] for row in comparative)
    assert result.model_dump_json() == before


def test_same_page_same_row_label_and_period_still_keep_distinct_table_columns():
    result, brief = mixed_tables()
    inventory = source_audit_scope(brief.items[0], result)
    inventory[1]['page'] = inventory[0]['page']
    inventory[1]['row_labels'] = inventory[0]['row_labels'][:]
    # Distinct measures within one period remain separate even within one table.
    inventory[0]['columns'].append({**inventory[0]['columns'][0],
        'column': 3, 'status': 'unknown', 'column_label': 'Separate measure'})
    options = [row for row in audit_status_options(brief.items[0], result, inventory=inventory)
               if row['period'] == '6M2023']
    assert len(options) == 3
    assert [(row['source_table_id'], row['source_column_index'], row['status']) for row in options] == [
        ('fees', 1, 'unaudited'), ('fees', 3, 'unknown'), ('unit-prices', 1, 'unknown')]


def test_unquoted_or_invented_column_label_never_appears_as_source_measure():
    result, brief = mixed_tables()
    result.document.pages[0].tables[0].headers[1] = 'Invented assurance measure'
    fee = audit_status_options(brief.items[0], result)[0]
    assert fee['source_column_label'] == ''
    assert fee['status'] == 'unaudited'  # Independently verified period geometry is retained.


@pytest.mark.parametrize('status', ['audited', 'unaudited'])
def test_cross_table_options_do_not_approve_an_unowned_period_status(status):
    result, brief = mixed_tables()
    brief.items[0].text = f'Programme prices were USD6 thousand per unit in {status} 6M2023.'
    assert audit_status_errors(brief.items[0], result)
    assert any(row['status'] == 'unknown' and not row['allowed_spellings']
               for row in audit_status_options(brief.items[0], result))


GOOD = ('Unaudited programme fees were USD1,250 thousand in 6M2023. '
        'Programme prices were USD6 thousand per unit in 6M2023.')


def repair(result, brief, replies, *, accept=True):
    reviewed, audit = [], {}
    def independent(value):
        reviewed.append(deepcopy(value))
        return {} if accept and value.items[0].text == GOOD else {
            0: ['The fee comparative requires its own assurance qualification; price assurance is unknown.']}
    corrected = correct_new_meaning_errors(replies, brief, result=result,
        excerpts={page.page_number: page.text for page in result.document.pages},
        topics=[], source_context={}, evidence_catalog=None,
        semantic_validator=independent, audit=audit)
    return corrected, audit['post_source_meaning_correction'], reviewed


def test_contract_retry_removes_new_amount_but_keeps_owned_status_and_fresh_review():
    result, brief = mixed_tables()
    assert not validate_executive_brief(brief, result)
    before = brief.model_dump_json()
    replies = Replies([{'item_0': {'text': GOOD + ' Another amount was USD1,475 thousand.'}},
                       {'item_0': {'text': GOOD}}])
    corrected, audit, reviewed = repair(result, brief, replies)
    assert corrected is not None and corrected.items[0].text == GOOD
    assert len(replies.calls) == 2 and len(reviewed) == 2
    assert audit['status'] == 'accepted' and audit['errors_after'] == []
    feedback = audit['contract_failures'][0]['feedback']['item_0']
    options = feedback['source_status_options']
    assert {(row['source_table_id'], row['status']) for row in options
            if row['period'] == '6M2023'} == {('fees', 'unaudited'), ('unit-prices', 'unknown')}
    assert 'neither cancels' in feedback['source_status_scope_rule']
    first_payload = json.loads(replies.calls[0][0][1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert first_payload['source_status_options']['item_0'] == options
    assert 'preserve the retained measure and its own qualification' in replies.calls[1][0][-1]['content']
    assert brief.model_dump_json() == before
    assert corrected.items[0].evidence == brief.items[0].evidence


@pytest.mark.parametrize('final_text', [
    'Programme fees were USD1,250 thousand in 6M2023. Programme prices were USD6 thousand per unit in 6M2023.',
    'Programme fees were USD1,250 thousand in 6M2023. Unaudited programme prices were USD6 thousand per unit in 6M2023.',
])
def test_missing_or_transferred_qualification_still_fails_fresh_review(final_text):
    result, brief = mixed_tables()
    replies = Replies([{'item_0': {'text': final_text}}])
    corrected, audit, reviewed = repair(result, brief, replies)
    assert corrected is None and audit['status'] == 'rejected'
    assert len(reviewed) == 2 and len(replies.calls) == 1


def test_supported_status_options_cannot_override_independent_reviewer_rejection():
    result, brief = mixed_tables()
    corrected, audit, reviewed = repair(result, brief, Replies([{'item_0': {'text': GOOD}}]), accept=False)
    assert corrected is None and audit['errors_after']
    assert len(reviewed) == 2
