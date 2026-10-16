"""Split source headers and literal reported deltas keep their exact evidence."""
import pytest

from adaptive_document_agent.agent.brief_meaning_review import MeaningComparison, comparison_errors, meaning_validator
from adaptive_document_agent.models import TableRow
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from adaptive_document_agent.services.brief_table_evidence import canonical_quantity, quoted_table_context
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_brief_table_context import table_result
from tests.test_executive_brief import result_for


def split_headers():
    result, brief = table_result()
    header = 'For the year ended December 31,\n2023 2024\nUSD % USD %\n(in thousands, except for percentages)'
    row = 'Programme fees 1,250 20.0 1,475 30.0'
    page, table = result.document.pages[0], result.document.pages[0].tables[0]
    page.text = header + '\n' + row
    table.headers = ['label', 'Amount', '%', 'Amount', '%']
    table.column_types = ['label', 'amount', 'percentage', 'amount', 'percentage']
    table.column_currencies = [None, 'USD', None, 'USD', None]
    table.column_scales = [None, 1000, 1, 1000, 1]
    table.default_raw_unit = 'USD'
    table.raw_header_lines = header.splitlines()
    table.rows = [TableRow(cells=['Programme fees', '1,250', '20.0', '1,475', '30.0'],
                           page=1, alignment_status='resolved')]
    brief.items[0].text = 'Programme fees were USD 1,475 thousand.'
    brief.items[0].evidence[0].text = page.text
    return result, brief


def test_exact_quoted_currency_columns_and_separate_scale_support_native_amounts():
    result, brief = split_headers()
    before = result.model_dump_json()
    assert canonical_quantity('USD', '1475', 'thousand') in quoted_table_context(brief.items[0], result).quantities
    assert not validate_executive_brief(brief, result)
    assert result.model_dump_json() == before


@pytest.mark.parametrize('fault', ['currency', 'scale', 'width', 'types', 'currency_not_quoted',
                                 'scale_not_quoted', 'disjoint', 'conflicting_scale', 'conflicting_currency',
                                 'partial_row', 'neighboring_table', 'mixed_currency', 'percentage_amount'])
def test_split_unit_recovery_cannot_borrow_or_invent_column_support(fault):
    result, brief = split_headers()
    page, table = result.document.pages[0], result.document.pages[0].tables[0]
    if fault == 'currency':
        brief.items[0].text = brief.items[0].text.replace('USD', 'EUR')
    elif fault == 'scale':
        brief.items[0].text = brief.items[0].text.replace('thousand', 'million')
    elif fault == 'mixed_currency':
        page.text = page.text.replace('USD % USD %', 'USD % EUR %')
        table.raw_header_lines[2] = 'USD % EUR %'
        brief.items[0].evidence[0].text = page.text
    elif fault == 'percentage_amount':
        brief.items[0].text = 'Programme fees were USD 30 thousand.'
    elif fault == 'width':
        page.text = page.text.replace('USD % USD %', 'USD USD')
        table.raw_header_lines[2] = 'USD USD'
        brief.items[0].evidence[0].text = page.text
    elif fault == 'types':
        table.column_types = ['label', 'percentage', 'amount', 'percentage', 'amount']
    elif fault in {'currency_not_quoted', 'scale_not_quoted'}:
        value = 'USD % USD %' if fault == 'currency_not_quoted' else '(in thousands, except for percentages)'
        page.text = page.text.replace(value + '\n', value + '\nAn intervening separate source passage.\n')
        brief.items[0].evidence[0].text = page.text.split('An intervening separate source passage.\n')[1]
    elif fault == 'disjoint':
        header, row = page.text.rsplit('\n', 1)
        page.text = header + '\nA separate unsupported intervening paragraph.\n' + row
        brief.items[0].evidence = [BriefQuote(page=1, text=header), BriefQuote(page=1, text=row)]
    elif fault in {'conflicting_scale', 'conflicting_currency'}:
        extra = '(in millions, except for percentages)' if fault == 'conflicting_scale' else 'EUR % EUR %'
        table.raw_header_lines.append(extra)
        page.text = page.text.replace('Programme fees', extra + '\nProgramme fees')
        brief.items[0].evidence[0].text = page.text
    elif fault == 'partial_row':
        brief.items[0].evidence[0].text = page.text.rsplit(' 30.0', 1)[0]
    else:
        table.raw_header_lines = table.raw_header_lines[:2]
        other = table.model_copy(deep=True)
        other.table_id = 'neighbor'
        other.raw_header_lines = page.text.splitlines()[2:4]
        other.rows = [TableRow(cells=['Unrelated fees', '1,250', '20.0', '1,475', '30.0'],
                               page=1, alignment_status='resolved')]
        page.tables.append(other)
    assert validate_executive_brief(brief, result)


def delta(claim='Deposits increased by USD12 million.', **updates):
    source = 'The increase in deposits was due to an increase of USD12 million.'
    comparison = MeaningComparison(claim=claim, comparison_kind='reported_delta',
        direction='increase', delta_value='USD12 million', delta_context=source,
        delta_quote=source, source_direction='increase')
    item = ExecutiveBriefItem(label='Deposit movement', text=claim,
                               evidence=[BriefQuote(page=1, text=source)])
    return comparison.model_copy(update=updates), item


def test_literal_reported_change_needs_no_invented_equal_endpoint_levels():
    comparison, item = delta()
    assert not comparison_errors(comparison, item)
    broken = comparison.model_copy(update={'comparison_kind': 'endpoints', 'start_value': '12',
        'end_value': '12', 'start_context': comparison.delta_context, 'end_context': comparison.delta_context})
    assert any('direction' in error for error in comparison_errors(broken, item))


@pytest.mark.parametrize('fault', ['changed_amount', 'changed_scale', 'level', 'wrong_source',
                                 'invented_endpoints', 'wrong_direction', 'missing_direction',
                                 'absolute', 'duration', 'source_percentage', 'unrelated_delta'])
def test_reported_delta_does_not_relax_native_quantity_source_or_direction_contract(fault):
    comparison, item = delta()
    updates = {
        'changed_amount': {'delta_value': 'USD13 million'},
        'changed_scale': {'delta_value': 'USD12000 thousand'},
        'level': {'claim': 'Deposits rose to USD12 million.'},
        'wrong_source': {'delta_quote': 'The increase was USD12 million elsewhere.'},
        'invented_endpoints': {'start_value': '0', 'end_value': '12'},
        'wrong_direction': {'direction': 'decrease'},
        'missing_direction': {'source_direction': None},
        'absolute': {'absolute_magnitude': True},
        'duration': {'start_duration_months': 12, 'end_duration_months': 9},
        'source_percentage': {'measure_basis': 'source_percentage'},
        'unrelated_delta': {'claim': 'Deposits rose to USD12 million by USD2 million.'},
    }[fault]
    comparison = comparison.model_copy(update=updates)
    if 'claim' in updates:
        item.text = updates['claim']
    assert comparison_errors(comparison, item)


def test_reported_delta_ref_is_bound_and_validated_through_normal_independent_review():
    comparison, item = delta()
    original = item.model_dump_json()
    reply = dict(index=0, accepted=True, reason='The exact reported increase matches the quoted source.',
        numeric_comparison=True, comparisons=[comparison.model_dump(exclude={'delta_context'}) | {'delta_ref': 'i0_q0'}])
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            return schema.model_validate({'items': [reply]})
    brief = ExecutiveBrief(items=[item])
    assert meaning_validator(Gateway(), result=result_for([item.evidence[0].text]))(brief) == {}
    assert item.model_dump_json() == original
    reply['comparisons'][0]['delta_ref'] = 'i1_q0'
    assert meaning_validator(Gateway(), result=result_for([item.evidence[0].text]))(brief)


@pytest.mark.parametrize('value', ['12', '12.0', 'USD12 thousand', 'EUR12 million'])
def test_reported_delta_cannot_strip_or_borrow_currency_or_scale_from_another_source_claim(value):
    comparison, item = delta(delta_value=value)
    source = 'Deposits increased by EUR12 thousand. Investments increased by USD12 million.'
    item.evidence[0].text = source
    comparison = comparison.model_copy(update={'delta_context': source,
        'delta_quote': 'Deposits increased by EUR12 thousand.'})
    assert comparison_errors(comparison, item)


@pytest.mark.parametrize('claim', [
    'The asset was acquired by USD12 million of cash consideration.',
    'The asset was purchased by USD12 million of cash consideration.',
    'Deposits increased by USD2 million and the asset was acquired by USD12 million.',
    'Deposits increased by USD2 million. Financial assets by USD12 million.',
    'Financial assets by USD12 million.',
])
def test_by_requires_own_actual_change_predicate_or_a_bound_shared_predicate(claim):
    comparison, item = delta(claim)
    item.evidence[0].text = claim
    comparison = comparison.model_copy(update={'delta_context': claim, 'delta_quote': claim})
    assert comparison_errors(comparison, item)


@pytest.mark.parametrize('predicate', ['increased', 'decreased', 'rose', 'fell', 'grew',
    'declined', 'reduced', 'shrank', 'widened', 'narrowed', 'expanded', 'contracted',
    'climbed', 'dropped', 'increased substantially'])
def test_reported_delta_accepts_normal_change_predicate_forms(predicate):
    claim = f'Deposits {predicate} by USD12 million.'
    comparison, item = delta(claim)
    item.evidence[0].text = claim
    comparison = comparison.model_copy(update={'delta_context': claim, 'delta_quote': claim})
    assert not comparison_errors(comparison, item)


def test_shared_predicate_requires_full_exact_claim_not_detached_second_noun_phrase():
    claim = 'Restricted cash increased by USD2 million and financial assets by USD12 million.'
    comparison, item = delta(claim)
    item.evidence[0].text = claim
    comparison = comparison.model_copy(update={'delta_context': claim, 'delta_quote': claim})
    assert not comparison_errors(comparison, item)
    assert comparison_errors(comparison.model_copy(update={'claim': 'financial assets by USD12 million.'}), item)
    assert comparison_errors(comparison.model_copy(update={'delta_quote': 'financial assets by USD12 million.'}), item)


def test_bare_reported_count_matches_equivalent_coefficient_without_monetary_units():
    claim = 'Store closures increased by 12.'
    comparison, item = delta(claim, delta_value='12.0', delta_context=claim, delta_quote=claim)
    item.evidence[0].text = claim
    assert not comparison_errors(comparison, item)


@pytest.mark.parametrize('source', [
    'There was an increase in profit. Closing balance of USD12 million.',
    'There was an increase in profit; closing balance of USD12 million.',
    'An increase in profit was followed by a closing balance of USD12 million.',
])
def test_of_cannot_borrow_an_earlier_change_noun_for_a_reported_level(source):
    comparison, item = delta(delta_context=source, delta_quote=source)
    item.evidence[0].text = source
    assert comparison_errors(comparison, item)


@pytest.mark.parametrize('source', ['An increase of USD12 million.',
    'An increase in deposits of USD12 million.',
    'An increase in restricted cash and time deposits of USD12 million.'])
def test_of_amount_remains_supported_by_its_own_immediate_change_noun(source):
    comparison, item = delta(delta_context=source, delta_quote=source)
    item.evidence[0].text = source
    assert not comparison_errors(comparison, item)


@pytest.mark.parametrize(('claim', 'source', 'value'), [
    ('Revenue increased by 12%.', 'Revenue increased by 12%.', '12%'),
    ('A 12.0% increase in revenue was reported.', 'Revenue increased by 12%.', '12.0%'),
    ('Revenue increased by 12 percent.', 'Revenue increased by 12%.', '12%'),
])
def test_exact_literal_reported_percentage_change_preserves_its_unit(claim, source, value):
    comparison, item = delta(claim, delta_value=value, delta_context=source, delta_quote=source)
    item.evidence[0].text = source
    assert not comparison_errors(comparison, item)


@pytest.mark.parametrize(('claim', 'source', 'value'), [
    ('Revenue increased by 12%.', 'Revenue increased by 12%.', '12'),
    ('Revenue increased by 12.', 'Revenue increased by 12%.', '12%'),
    ('Revenue increased by 12%.', 'Revenue increased by 12.', '12%'),
    ('Revenue increased by 12 percentage points.', 'Revenue increased by 12%.', '12%'),
    ('Revenue increased by 12%.', 'Revenue increased by 12 percentage points.', '12%'),
    ('Revenue increased by 12%.', 'Revenue increased by 12 basis points.', '12%'),
    ('Revenue increased by 12.', 'Revenue increased by 12 percentage points.', '12'),
    ('Revenue increased by USD12 million.', 'Revenue increased by 12%.', '12%'),
    ('Revenue increased by 12%.', 'Revenue increased by USD12 million.', '12%'),
    ('Revenue increased by 12%.', 'Revenue was 12%.', '12%'),
    ('Revenue increased by 12% in 2024.', 'Revenue increased by 12% in 2024.', '2024'),
])
def test_reported_percentage_cannot_be_bare_money_points_a_level_or_a_calendar_year(claim, source, value):
    comparison, item = delta(claim, delta_value=value, delta_context=source, delta_quote=source)
    item.evidence[0].text = source
    assert comparison_errors(comparison, item)


def test_reported_percentage_keeps_same_duration_and_exact_direction_requirements():
    source = 'Revenue increased by 12%.'
    comparison, item = delta(source, delta_value='12%', delta_context=source, delta_quote=source)
    item.evidence[0].text = source
    assert comparison_errors(comparison.model_copy(update={
        'start_duration_months': 6, 'end_duration_months': 12}), item)
    assert comparison_errors(comparison.model_copy(update={'direction': 'decrease'}), item)


def test_absolute_outflow_magnitude_direction_stays_independent_of_signed_direction():
    source = 'Investing cash flow was (20) and (30) in the two same-duration periods.'
    item = ExecutiveBriefItem(label='Outflow', text='Outflow widened from 20 to 30.',
                              evidence=[BriefQuote(page=1, text=source)])
    comparison = MeaningComparison(claim=item.text, start_value='-20', end_value='-30',
        direction='increase', absolute_magnitude=True, start_context=source, end_context=source,
        start_duration_months=9, end_duration_months=9)
    assert not comparison_errors(comparison, item)
    assert any('direction' in error for error in comparison_errors(
        comparison.model_copy(update={'direction': 'decrease'}), item))


@pytest.mark.parametrize('diagnostic', ['increase', 'decrease', 'equal', None])
def test_endpoint_source_direction_diagnostic_never_replaces_bound_arithmetic(diagnostic):
    source = 'Deposits were 20 and 30 in the two same-duration periods.'
    item = ExecutiveBriefItem(label='Deposits', text='Deposits rose from 20 to 30.',
                              evidence=[BriefQuote(page=1, text=source)])
    comparison = MeaningComparison(claim=item.text, start_value='20', end_value='30',
        start_context=source, end_context=source, direction='increase', source_direction=diagnostic)
    assert not comparison_errors(comparison, item)
    assert any('direction' in error for error in comparison_errors(
        comparison.model_copy(update={'direction': 'decrease'}), item))
    for field in ['delta_value', 'delta_ref', 'delta_context', 'delta_quote']:
        assert any('unrelated reported-change' in error for error in comparison_errors(
            comparison.model_copy(update={field: 'unrelated'}), item))


def test_literal_narrative_total_does_not_authorize_new_component_counts_in_meaning_patch():
    from adaptive_document_agent.agent.brief_meaning_contract import check_meaning_contract
    source = 'The table shows 12 closed by the operator and 28 by partners. The narrative states 40 closures.'
    item = ExecutiveBriefItem(label='Closures', text='The narrative reports 40 closures.',
                              evidence=[BriefQuote(page=1, text=source)])
    original = ExecutiveBrief(items=[item])
    candidate = original.model_copy(deep=True)
    candidate.items[0].text = 'The narrative reports 40 closures (12 by the operator and 28 by partners).'
    _, errors, _, recoverable = check_meaning_contract(original, candidate, [0],
        result=result_for([source]), excerpts={1: source}, inventories={0: []}, periods={0: []})
    assert errors and 'new quantities' in errors[0] and not recoverable
