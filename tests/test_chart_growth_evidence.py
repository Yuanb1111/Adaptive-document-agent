from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support
from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
from adaptive_document_agent.extraction.chart_growth_evidence import chart_growth_observations
from adaptive_document_agent.models import DocumentPage, ExtractedTable, TableRow
from adaptive_document_agent.services.presentation_evidence import calculation_catalog
from tests.test_topic_coverage_review import _observation


@pytest.fixture
def source():
    periods = ['2019', '2020', '2021', '2022', '2023', '2028E']
    values = [27.2, 31.3, 47.2, 70.4, 75.7, 373.2]
    labels = [
        ('CAGR 2019-2023', [145, 30, 185, 37]),
        ('CAGR 2023-2028E', [205, 30, 245, 37]),
        ('Health', [100, 45, 130, 52]),
        ('29.1%', [155, 45, 174, 52]),
        ('37.6%', [215, 45, 234, 52]),
        ('US$ million', [20, 48, 55, 55]),
        *((p, [x, 100, x + 20, 107]) for p, x in zip(periods, range(65, 245, 30))),
        ('Health', [10, 120, 35, 127]),
    ]
    page = DocumentPage(page_number=234, text='\n'.join(s for s, _ in labels),
        text_blocks=[dict(lines=[dict(text=text, bbox=box) for text, box in labels])],
        tables=[ExtractedTable(table_id='source', page=234, bbox=(0, 0, 300, 140),
            headers=['label', *periods], column_periods=[None, *periods], column_types=['label', *(['amount'] * 6)],
            rows=[TableRow(cells=['Health', *(str(v) for v in values)], page=234)])])
    page.text += '\nHealth ' + ' '.join(str(v) for v in values)
    observations = [_observation('Health', p, v).model_copy(update=dict(
        unit='unknown', raw_unit=None, row_id=0, column_id=i))
        for i, (p, v) in enumerate(zip(periods, values), 1)]
    return SimpleNamespace(pages=[page]), observations


def test_binds_the_chart_unit_reported_rate_and_recalculation_separately(source):
    document, raw = source
    bound = chart_growth_observations(document, raw)
    actuals = [o for o in bound if o.period in {'2019','2020','2021','2022','2023'}]
    reported, = [o for o in bound if o.period == '2019–2023']
    assert [o.raw_value for o in actuals] == [o.raw_value for o in raw[:5]]
    assert actuals[0].value == 27_200_000 and actuals[0].raw_unit == 'US$ million'
    assert actuals[0].evidence[-1].bbox == (20, 48, 55, 55)
    assert reported.raw_value == '29.1%' and reported.evidence[0].bbox == (155,45,174,52)
    rate, = [c for c in calculation_catalog(actuals).values() if c['kind'] == 'cagr']
    assert rate['value'] == pytest.approx(29.16110262856384)
    assert rate['observation_ids'] == [o.id for o in actuals]
    assert format_observation_period(actuals[0]) == '2019'
    assert raw[0].value == 27.2 and raw[0].unit == 'unknown'
    assert chart_growth_observations(document, bound) == bound


@pytest.mark.parametrize('text,accepted', [
    ('The chart reports 29.1% CAGR for 2019 to 2023.', True),
    ('The recalculated CAGR for 2019 to 2023 is 29.2%.', True),
    ('The chart reports 29.2% CAGR for 2019 to 2023.', False),
    ('The recalculated CAGR for 2019 to 2023 is 29.1%.', False),
    ('The chart reports 29.1% CAGR for 2020 to 2023.', False),
    ('The CAGR is 29.1%.', False),
    ('Revenue grew by 29.1%.', False),
    ('Revenue was US$27.2 million in 2019.', True),
    ('The chart is in HK$ million.', False),
    ('The chart is in US$ thousand.', False),
])
def test_cagr_claims_cannot_borrow_the_other_rate_or_currency(source, text, accepted):
    document, raw = source
    bound = [o for o in chart_growth_observations(document, raw) if o.period.isdigit() or o.period == '2019–2023']
    assert _numeric_support(text, bound) is accepted


def test_saved_chart_currency_symbol_matches_the_original_axis_unit(source):
    document, raw = source
    bound = [o.model_copy(update={'currency': 'US$'}) for o in chart_growth_observations(document, raw)
             if o.currency]
    assert _numeric_support('The chart labels revenue in US$ million.', bound)
    assert not _numeric_support('The chart labels revenue in HK$ million.', bound)
    assert not _numeric_support('The chart labels revenue in US$ thousand.', bound)


def test_ambiguous_axis_leaves_cells_unchanged(source):
    document, raw = source
    document.pages[0].text_blocks[0]['lines'].append(dict(text='HK$ million', bbox=[20, 57, 56, 63]))
    assert chart_growth_observations(document, raw) == raw


def test_saved_amount_task_is_not_rescaled(source):
    document, raw = source
    saved = SimpleNamespace(task_id='amount', input_observation_ids=[o.id for o in raw[:5]])
    tool = SimpleNamespace(id='amount', tool_name='absolute_change')
    bound = chart_growth_observations(document, raw, analysis_plan=[tool], analysis_results=[saved])
    assert bound[:5] == raw[:5]
    assert bound[-2].raw_value == '29.1%'


def test_brief_currency_requires_both_the_axis_and_exact_quoted_row(source):
    from adaptive_document_agent.models.executive_brief import BriefQuote
    from adaptive_document_agent.services.brief_table_evidence import quoted_table_context

    document, raw = source
    result = SimpleNamespace(document=document, observations=chart_growth_observations(document, raw))
    row = document.pages[0].text.splitlines()[-1]
    item = SimpleNamespace(evidence=[BriefQuote(page=234, text=row)])
    assert not quoted_table_context(item, result).quantities
    item.evidence.append(BriefQuote(page=234, text='US$ million'))
    assert ('us$', '27.2', 'million') in quoted_table_context(item, result).quantities
