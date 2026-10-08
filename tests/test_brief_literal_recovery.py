"""Complete literal evidence can be split; content and validation cannot change."""
import copy
import json

import pytest

from adaptive_document_agent.agent.brief_quote_bounds import bounded_quote_item
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_brief_item_repair import audited, item
from tests.test_executive_brief import gateway, result_for
from tests.test_brief_table_context import table_result


def long_source():
    return 'Revenue was USD 12 million. ' + 'The estimate remains conditional on delivery. ' * 45


def test_complete_overlong_quote_recovers_without_model_retry_and_retains_raw_audit():
    source = long_source()
    original = {'title': 'Findings', 'items': [item('Revenue was USD 12 million.')]}
    original['items'][0]['evidence'][0]['text'] = source
    before = copy.deepcopy(original)
    result = result_for([source])
    g, client = gateway([original])
    brief = ExecutiveBriefWriter(g).generate(result)
    quotes = brief.items[0].evidence
    assert len(quotes) == 2 and all(len(q.text) <= 1800 for q in quotes)
    assert ' '.join(q.text for q in quotes).strip() == source.strip()
    assert not validate_executive_brief(brief, result)
    assert len(client.calls) == 1 and original == before
    assert audited(result)['original'] == original
    assert audited(result)['outcome'] == 'quote_reformatted'


@pytest.mark.parametrize('mutation', ['wrong_page', 'missing_words', 'capacity', 'extra_field'])
def test_quote_reformatting_never_trims_or_invents_support(mutation):
    source = long_source()
    value = item('Revenue was USD 12 million.')
    value['evidence'][0]['text'] = source
    if mutation == 'wrong_page': value['evidence'][0]['page'] = 2
    if mutation == 'missing_words': source = source.replace('conditional on delivery', 'conditional on audited delivery')
    if mutation == 'capacity': value['evidence'] += [{'page': 1, 'text': 'Revenue was USD 12 million.'}] * 3
    if mutation == 'extra_field': value['evidence'][0]['unknown'] = True
    before = copy.deepcopy(value)
    assert bounded_quote_item(value, {1: source}) == before
    assert value == before


def test_overlong_patch_recovers_two_item_brief_without_displacing_lock():
    source = long_source()
    cash = 'Cash was USD 4 million.'
    bad = item('Revenue was USD 99 million.')
    bad['evidence'][0]['text'] = 'Revenue was USD 12 million.'
    original = {'title': 'Findings', 'items': [item(cash), bad]}
    corrected = item('Revenue was USD 12 million.')
    corrected['evidence'][0]['text'] = source
    result = result_for([source + cash])
    g, client = gateway([original, {'item_1': corrected}])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert len(brief.items) == 2 and len(client.calls) == 2
    assert brief.items[0].model_dump() == original['items'][0]
    assert brief.items[1].text == corrected['text']
    assert audited(result)['patch_response'] == json.dumps({'item_1': corrected}, ensure_ascii=False)
    assert audited(result)['outcome'] == 'repaired'
    assert not validate_executive_brief(brief, result)


def test_reformatted_verified_lock_survives_successful_two_item_patch():
    source = long_source()
    original = {'title': 'Findings', 'items': [item('Revenue was USD 12 million.'), item('Cash was 99.')]}
    original['items'][0]['evidence'][0]['text'] = source
    original['items'][1]['evidence'][0]['text'] = 'Cash was 4.'
    result = result_for([source + ' Cash was 4.'])
    g, client = gateway([original, {'item_1': item('Cash was 4.')}])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert len(brief.items) == 2 and len(brief.items[0].evidence) == 2
    assert brief.items[1].text == 'Cash was 4.'
    assert audited(result)['locked_indices'] == [0] and audited(result)['outcome'] == 'repaired'
    assert len(client.calls) == 2 and not validate_executive_brief(brief, result)


@pytest.mark.parametrize('period', ['1H2025', 'H12025', '2H2025', 'H22025'])
def test_half_year_labels_do_not_create_measurements(period):
    assert not {'1', '2'} & PresentationPlanValidator._numbers(f'Revenue in {period} was 12.')


def test_accounting_scale_outside_parentheses_preserves_sign():
    result, brief = table_result()
    result.document.pages[0].text = 'USD in thousands\nNet loss (100) (200)'
    table = result.document.pages[0].tables[0]
    table.rows[0].cells = ['Net loss', '(100)', '(200)']
    table.raw_header_lines = ['USD in thousands']
    brief.items[0].evidence[0].text = 'Net loss (100) (200)'
    brief.items[0].text = 'Net loss was USD(100) thousand.'
    assert not validate_executive_brief(brief, result)
    brief.items[0].text = 'Net loss was USD 100 thousand.'
    assert validate_executive_brief(brief, result)


def test_identical_complete_rows_share_only_identical_column_bindings():
    result, brief = table_result()
    other = result.document.pages[0].tables[0].model_copy(deep=True)
    other.table_id = 'duplicate-source-row'
    result.document.pages[0].tables.append(other)
    assert not validate_executive_brief(brief, result)
    other.column_periods = [None, '2022', '2025']
    assert validate_executive_brief(brief, result)


def test_one_malformed_patch_item_cannot_discard_other_verified_replacements():
    sources = ['Revenue was 12.', 'Costs were 8.', 'Cash was 4.', 'Debt was 6.', 'Output was 20.']
    original = {'title': 'Findings', 'items': [item(text) for text in sources]}
    original['items'][3]['text'] = 'Debt was 99.'
    original['items'][4]['text'] = 'Output was 99.'
    bad = item(sources[3])
    bad['evidence'][0]['text'] = 'A passage that is absent from the original source. ' * 50
    result = result_for([' '.join(sources)])
    g, client = gateway([original, {'item_3': bad, 'item_4': item(sources[4])}])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert [i.text for i in brief.items] == [*sources[:3], sources[4]]
    assert [i.model_dump() for i in brief.items[:3]] == original['items'][:3]
    assert audited(result)['outcome'] == 'salvaged' and audited(result)['partial_patch_items'] == [4]
    assert audited(result)['discarded_indices'] == [3]
    assert len(client.calls) == 2 and not validate_executive_brief(brief, result)


def test_split_quote_keeps_full_conditional_completeness_gate():
    source = ('Context applies. ' * 103
              + 'Response time is estimated at 44 months without expansion, '
              + '60 months with partial expansion and 89 months with full expansion.')
    value = item('Response time depends on expansion assumptions.')
    value['evidence'][0]['text'] = source
    value['comparison_table'] = {'headers': ['Assumption', 'Response time'],
                                'rows': [['with partial expansion', '60 months'],
                                         ['with full expansion', '89 months']]}
    value = bounded_quote_item(value, {1: source})
    assert len(value['evidence']) == 2
    result = result_for([source])
    brief = ExecutiveBrief.model_validate({'title': 'Scenarios', 'items': [value]})
    assert any('omits a quoted conditional outcome' in e for e in validate_executive_brief(brief, result))
    brief.items[0].comparison_table.rows.insert(0, ['without expansion', '44 months'])
    assert not validate_executive_brief(brief, result)


def test_percentage_units_bind_complete_rows_without_accepting_mixed_unit_ambiguity():
    from adaptive_document_agent.services.executive_brief import brief_items
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.rows[0].cells = ['Survey response', '62.5', '44.25']
    table.column_types = ['label', 'percentage', 'percentage']
    table.column_currencies = [None, None, None]
    table.column_scales = [None, 1, 1]
    table.raw_header_lines = ['(%)']
    result.document.pages[0].text = '(%)\nSurvey response 62.5 44.25'
    brief.items[0].evidence[0].text = 'Survey response 62.5 44.25'
    brief.items[0].text = 'Survey response was 62.5%.'
    assert not validate_executive_brief(brief, result)
    result.executive_brief = brief
    brief.items[0].text = 'Survey response was 62.5.'
    assert '62.5%' in brief_items(result)[0].text
    table.rows[0].cells.append('62.5')
    table.column_types.append('amount')
    result.document.pages[0].text += ' 62.5'
    brief.items[0].evidence[0].text += ' 62.5'
    brief.items[0].text = 'Survey response was 62.5%.'
    assert validate_executive_brief(brief, result)
