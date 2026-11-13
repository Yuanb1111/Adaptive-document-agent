"""A cumulative change is not a level or a reported/annualized growth rate."""
import pytest

from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support
from adaptive_document_agent.extraction.chart_growth_evidence import chart_growth_observations
from tests.test_chart_growth_evidence import source


@pytest.mark.parametrize('rate,start,end,kind,accepted',[
    ('200.0','2021-12-31','2024-10-31','increase',True),
    ('200.1','2021-12-31','2024-10-31','increase',False),
    ('200.0','2021-12-30','2024-10-31','increase',False),
    ('200.0','2024-10-31','2021-12-31','increase',False),
    ('200.0','2021-12-31','2024-10-31','decrease',False),
])
def test_calculated_percentage_uses_complete_exact_balance_sheet_dates(rate,start,end,kind,accepted):
    from tests.test_declared_calculated_amount import rows
    assert _numeric_support(f'The calculated {kind} was {rate}% from {start} to {end}.',rows()) is accepted


@pytest.mark.parametrize('text,accepted',[
    ('The calculated cumulative increase was 178.3% from 2019 to 2023.',True),
    ('The calculated percentage increase in Health was 178.3% from 2019 to 2023.',True),
    ('The computed change was +178.3% from 2019 to 2023.',True),
    ('The calculated cumulative increase was 408.4% from 2019 to 2023.',False),
    ('The calculated cumulative increase was 178.3% from 2020 to 2023.',False),
    ('The calculated percentage increase in Margin was 178.3% from 2019 to 2023.',False),
    ('The calculated cumulative decrease was 178.3% from 2019 to 2023.',False),
    ('The calculated cumulative increase was -178.3% from 2019 to 2023.',False),
    ('The calculated annual growth was 178.3% from 2019 to 2023.',False),
    ('The calculated CAGR was 178.3% from 2019 to 2023.',False),
    ('The margin was 178.3% from 2019 to 2023.',False),
    ('The cumulative increase was 178.3% from 2019 to 2023.',False),
])
def test_label_requires_exact_calculation_kind_metric_interval_and_signed_direction(source,text,accepted):
    document,raw=source
    bound=[o for o in chart_growth_observations(document,raw)
           if o.period.isdigit() or o.period=='2019–2023']
    assert _numeric_support(text,bound) is accepted


@pytest.mark.parametrize('text,accepted',[
    ('The chart reports a CAGR of 29.1% for 2019–2023 and 37.6% for 2023–2028E.',True),
    ('The chart reports 2019–2023 CAGR of 29.1% and 2023–2028E CAGR of 37.6%.',True),
    ('The chart reports a CAGR of 37.6% for 2019–2023 and 29.1% for 2023–2028E.',False),
    ('The chart reports a CAGR of 29.1% for 2020–2023 and 37.6% for 2023–2028E.',False),
    ('The chart reports 2019–2023 CAGR 29.1% for 2023–2028E.',False),
    ('The chart reports CAGRs of 29.1% and 37.6% for 2019–2023 and 2023–2028E.',False),
    ('The chart reports a CAGR of 29.1% for 2019–2023 and a calculated CAGR of 37.6% for 2023–2028E.',False),
])
def test_each_listed_reported_cagr_has_one_exact_local_interval(source,text,accepted):
    document,raw=source
    assert _numeric_support(text,chart_growth_observations(document,raw)) is accepted
