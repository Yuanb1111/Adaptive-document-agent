"""A relative date is not a new table cell; correction remains bounded and reviewed."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_audit_scope import (
    audit_status_errors, misplaced_parenthetical_statuses, source_audit_scope,
)
from adaptive_document_agent.agent.brief_period_clarification import period_clarification_options
from adaptive_document_agent.agent.brief_semantic_repair import correct_new_meaning_errors
from adaptive_document_agent.models import TableRow
from tests.test_brief_audit_scope_v146 import _case


def comparison_case():
    result, brief = _case()
    brief.items[0].text = ('Programme fees were USD 1,475 thousand in the six months ended June 30, 2024, '
                           'up from USD 1,250 thousand a year earlier.')
    return result, brief


GOOD = ('Programme fees were USD 1,475 thousand in the six months ended June 30, 2024, '
        'up from USD 1,250 thousand in the six months ended June 30, 2023 (unaudited).')
AMBIGUOUS = ('Programme fees were USD 1,475 thousand in the six months ended June 30, 2024 '
             '(unaudited: USD 1,250 thousand in the six months ended June 30, 2023).')


class Replies:
    def __init__(self, values):
        self.values, self.calls = iter(values), []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((deepcopy(messages), set(schema.model_fields)))
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return schema.model_validate(value)


def run(result, brief, replies, *, audit=None, reviewed=None):
    audit = {} if audit is None else audit
    def review(value):
        if reviewed is not None:
            reviewed.append(deepcopy(value))
        return {i: ['Retain the source period qualification.'] for i, item in enumerate(value.items)
                if 'unaudited' not in item.text}
    corrected = correct_new_meaning_errors(replies, brief, result=result,
        excerpts={p.page_number: p.text for p in result.document.pages}, topics=[], source_context={},
        evidence_catalog=None, semantic_validator=review, audit=audit)
    return corrected, audit['post_source_meaning_correction']


@pytest.mark.parametrize('prior', ['six months ended June 30, 2023', '6M2023', '1H2023'])
def test_explicit_source_bound_prior_year_date_can_qualify_existing_comparison(prior):
    result, brief = comparison_case()
    before = brief.model_dump(mode='json')
    assert period_clarification_options(brief.items[0], result)[0]['clarified_prior_period'] == '6M2023'
    replies = Replies([{'item_0': {'text': GOOD.replace('six months ended June 30, 2023', prior)}}])
    reviewed = []
    corrected, audit = run(result, brief, replies, reviewed=reviewed)
    assert corrected is not None and audit['status'] == 'accepted'
    assert len(replies.calls) == 1 and len(reviewed) == 2
    assert brief.model_dump(mode='json') == before
    assert corrected.items[0].evidence == brief.items[0].evidence


@pytest.mark.parametrize('text', [
    GOOD.replace('2023 (unaudited)', '2022 (unaudited)'),
    GOOD + ' The programme had 2023 participants.',
    GOOD.replace('six months ended June 30, 2023', 'three months ended June 30, 2023'),
    GOOD.replace('USD 1,250 thousand', 'USD 999 thousand'),
])
def test_period_exception_cannot_authorize_another_year_duration_count_or_money(text):
    result, brief = comparison_case()
    replies = Replies([{'item_0': {'text': text}}])
    corrected, audit = run(result, brief, replies)
    assert corrected is None and audit['status'] == 'rejected'
    assert len(replies.calls) == 1


def test_source_year_is_not_a_clarification_without_an_existing_relative_comparison():
    result, brief = comparison_case()
    brief.items[0].text = 'Programme fees were USD 1,475 thousand in the six months ended June 30, 2024.'
    assert not period_clarification_options(brief.items[0], result)
    replies = Replies([{'item_0': {'text': GOOD}}])
    assert run(result, brief, replies)[0] is None
    assert len(replies.calls) == 1


def test_misplaced_status_remains_invalid_until_model_places_it_on_source_period():
    result, brief = comparison_case()
    ambiguous = brief.items[0].model_copy(update={'text': AMBIGUOUS})
    assert audit_status_errors(ambiguous, result)
    feedback = misplaced_parenthetical_statuses(ambiguous, result)
    assert feedback[0]['supported_inner_period'] == '6M2023'
    assert feedback[0]['ambiguous_preceding_period'] == 'six months ended June 30, 2024'
    replies, reviewed = Replies([{'item_0': {'text': AMBIGUOUS}}, {'item_0': {'text': GOOD}}]), []
    corrected, audit = run(result, brief, replies, reviewed=reviewed)
    assert corrected and len(replies.calls) == 2 and len(reviewed) == 2
    assert audit['errors_after'] == [] and audit['contract_failures'][0]['errors']
    assert 'source-contract violations' in replies.calls[1][0][-1]['content']
    assert source_audit_scope(corrected.items[0], result)[0]['columns'][1]['status'] == 'unknown'


@pytest.mark.parametrize('remove', [True, False])
def test_new_quoted_table_amount_is_removed_by_model_or_rejected_never_granted(remove):
    result, brief = comparison_case()
    page, table = result.document.pages[0], result.document.pages[0].tables[0]
    table.rows.append(TableRow(cells=['Programme costs', '5,000', '6,000'], page=1, alignment_status='resolved'))
    page.text += '\nProgramme costs . . . 5,000 6,000'
    brief.items[0].evidence[0].text = page.text
    extra = GOOD + ' Programme costs were USD 6,000 thousand.'
    replies = Replies([{'item_0': {'text': extra}}, {'item_0': {'text': GOOD if remove else extra}}])
    corrected, audit = run(result, brief, replies)
    assert len(replies.calls) == 2
    assert (corrected is not None) is remove
    assert audit['contract_failures'][0]['feedback']['item_0']['new_table_quantities_to_remove']
    if corrected:
        assert '6,000' not in corrected.items[0].text
    else:
        assert 'introduced new quantities' in audit['errors_after'][0]


def test_contract_retry_locks_a_provisionally_corrected_other_item():
    result, brief = comparison_case()
    brief.items.append(brief.items[0].model_copy(update={'label': 'Separate source finding',
        'text': 'Programme fees were USD 1,250 thousand in 6M2023.'}))
    second = 'Programme fees were USD 1,250 thousand in 6M2023 (unaudited).'
    replies = Replies([{'item_0': {'text': AMBIGUOUS}, 'item_1': {'text': second}}, {'item_0': {'text': GOOD}}])
    corrected, audit = run(result, brief, replies)
    assert corrected and replies.calls[1][1] == {'item_0'}
    assert corrected.items[1].text == second and corrected.items[1].evidence == brief.items[1].evidence
    assert audit['errors_after'] == []


def test_protocol_and_contract_feedback_share_two_calls_and_never_start_another_review_loop():
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    result, brief = comparison_case()
    failure = LLMStructuredOutputError('Missing text', response=LLMResponse(text='{"item_0": {}}'))
    replies = Replies([failure, {'item_0': {'text': AMBIGUOUS}}])
    reviewed = []
    corrected, audit = run(result, brief, replies, reviewed=reviewed)
    assert corrected is None and len(replies.calls) == 2 and len(reviewed) == 1
    assert audit['protocol_failures'] and audit['errors_after']


def alias_contract(original, candidate, *, source=None):
    from adaptive_document_agent.agent.brief_meaning_contract import check_meaning_contract
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
    from tests.test_executive_brief import result_for
    source = source or 'Fees were USD12 million in the nine months ended September 30, 2024.'
    result = result_for([source])
    brief = ExecutiveBrief(items=[ExecutiveBriefItem(label='Fees', text=original,
        evidence=[BriefQuote(page=1, text=source)])])
    proposed = brief.model_copy(deep=True)
    proposed.items[0].text = candidate
    return check_meaning_contract(brief, proposed, [0], result=result, excerpts={1: source},
                                  inventories={0: []}, periods={0: []})[1]


@pytest.mark.parametrize(('original', 'candidate'), [
    ('Fees were USD12 million in 9M2024.',
     'Fees were USD12 million in the nine months ended September 30, 2024.'),
    ('Fees were USD12 million in 9M2024.',
     'Fees were USD12 million in the 9 months ended September 30, 2024.'),
    ('Fees were USD12 million in the nine months ended September 30, 2024.',
     'Fees were USD12 million in 9M2024.'),
])
def test_original_complete_period_aliases_are_not_new_measurements_without_table_inventory(original, candidate):
    assert not alias_contract(original, candidate)


@pytest.mark.parametrize('candidate', [
    'Fees were USD12 million in the eight months ended September 30, 2024.',
    'Fees were USD12 million in the nine months ended September 29, 2024.',
    'Fees were USD12 million in the nine months ended September 30, 2025.',
    'Fees were USD12 million in 9M2024. There were 9 participants.',
    'Fees were USD12 million in 9M2024. There were 2024 participants.',
    'Fees were USD12 million in the 19 months ended September 30, 2024.',
    'Fees were USD12 million in 9M2024. Costs were USD13 million.',
])
def test_original_period_alias_does_not_authorize_new_count_date_duration_year_or_money(candidate):
    assert alias_contract('Fees were USD12 million in 9M2024.', candidate)


def test_original_spelled_duration_does_not_grant_its_coefficient_to_a_new_count():
    original = 'Fees were USD12 million in the nine months ended September 30, 2024.'
    assert alias_contract(original, original + ' There were 9 participants.')


@pytest.mark.parametrize('source', [
    'Fees were USD12 million in 9M2024.',
    'Fees were USD12 million in the nine months ended September 30, 2024. '
    'Another programme used the nine months ended December 31, 2024.',
])
def test_compact_original_period_requires_unique_complete_source_closing_date(source):
    assert alias_contract('Fees were USD12 million in 9M2024.',
        'Fees were USD12 million in the nine months ended September 30, 2024.', source=source)


def test_half_year_alias_requires_its_actual_calendar_closing_date():
    assert not alias_contract('Fees were USD12 million in the six months ended June 30, 2024.',
                              'Fees were USD12 million in 1H2024.')
    assert alias_contract('Fees were USD12 million in the six months ended September 30, 2024.',
                          'Fees were USD12 million in 1H2024.')


def test_unusual_nine_month_closing_date_is_literal_not_assumed_september():
    source = 'Fees were USD12 million in the nine months ended November 15, 2024.'
    assert not alias_contract('Fees were USD12 million in 9M2024.', source, source=source)
    assert alias_contract('Fees were USD12 million in 9M2024.',
        source.replace('November 15', 'September 30'), source=source)


def geometry_alias_case():
    from adaptive_document_agent.models import TableRow
    result, brief = _case()
    page, table = result.document.pages[0], result.document.pages[0].tables[0]
    table.headers = ['label', 'Amount', 'Amount', 'Amount']
    table.column_periods = [None, 'FY2023', '9M2023', '9M2024']
    table.column_audit_statuses = ['unknown'] * 4
    table.raw_header_lines = ['For the nine months',
        'For the year ended December 31, ended November 15,', '2023 2023 2024']
    table.rows = [TableRow(cells=['Programme fees', '100', '1250', '1475'], page=1,
                           alignment_status='resolved')]
    table.bbox = (0, 100, 350, 160)
    page.text = '\n'.join(table.raw_header_lines) + '\nProgramme fees 100 1250 1475'
    page.text_blocks = [{'lines': [
        {'text': 'For the nine months', 'bbox': [225, 0, 275, 10]},
        {'text': 'For the year ended December 31,', 'bbox': [80, 12, 120, 22]},
        {'text': 'ended November 15,', 'bbox': [225, 12, 275, 22]},
        {'text': '2023', 'bbox': [90, 25, 110, 35]},
        {'text': '2023', 'bbox': [190, 25, 210, 35]},
        {'text': '2024', 'bbox': [290, 25, 310, 35]},
    ]}]
    brief.items[0].text = 'Programme fees were USD1475 thousand in 9M2024.'
    brief.items[0].evidence[0].text = page.text
    return result, brief


def test_split_table_geometry_keeps_annual_date_separate_from_interim_alias():
    from adaptive_document_agent.agent.brief_period_clarification import original_period_identities
    result, brief = geometry_alias_case()
    inventory = source_audit_scope(brief.items[0], result)
    before = result.model_dump_json()
    assert original_period_identities(brief.items[0], inventory, result=result) == {(9, '2024-11-15')}
    assert result.model_dump_json() == before


@pytest.mark.parametrize('fault', ['no_geometry', 'row_only', 'wrong_duration_column',
                                 'unquoted_duration', 'swapped_date_positions'])
def test_split_header_alias_cannot_borrow_missing_unquoted_or_conflicting_geometry(fault):
    from adaptive_document_agent.agent.brief_period_clarification import original_period_identities
    result, brief = geometry_alias_case()
    page, table = result.document.pages[0], result.document.pages[0].tables[0]
    if fault == 'no_geometry':
        page.text_blocks = []
    elif fault == 'row_only':
        brief.items[0].evidence[0].text = 'Programme fees 100 1250 1475'
    elif fault == 'wrong_duration_column':
        table.column_periods[-1] = '8M2024'
    elif fault == 'unquoted_duration':
        brief.items[0].evidence[0].text = page.text.split('\n', 1)[1]
    else:
        page.text_blocks[0]['lines'][1]['bbox'] = [225, 12, 275, 22]
        page.text_blocks[0]['lines'][2]['bbox'] = [80, 12, 120, 22]
    assert not original_period_identities(brief.items[0], source_audit_scope(brief.items[0], result), result=result)
