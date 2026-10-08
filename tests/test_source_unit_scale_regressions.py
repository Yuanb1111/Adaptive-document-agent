import pytest
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer


def table(headers,raw_headers,scales,**kwargs):
    return ExtractedTable(table_id='units',page=7,headers=headers,raw_header_lines=raw_headers,
        column_periods=[None,'FY2023'],column_scales=scales,column_types=['label','amount'],
        rows=[TableRow(page=7,cells=['Revenue','123'])],confidence=.9,**kwargs)


def test_bare_currency_column_inherits_source_thousands_not_unscaled_currency():
    t=table(['label','RMB'],['For the year ended December31','RMB in thousands'],[None,1000],
        default_currency='CNY',default_unit_scale=1000,default_unit='currency')
    before=t.model_dump();o=ObservationExtractor()._table_observations(t)[0]
    assert o.value==123000 and o.unit_scale==1000 and o.metric_original=='Revenue'
    assert o.raw_value=='123' and o.evidence[0].column_label=='RMB' and t.model_dump()==before


def test_separate_explicit_scale_header_overrides_narrative_millions():
    t=table(['label','Amount'],['RMB % RMB %','(in thousands, except for percentages)'],[None,1000000],
        default_currency='CNY',default_unit_scale=1000000,default_unit='currency')
    o=ObservationExtractor()._table_observations(t)[0]
    assert o.value==123000 and o.unit_scale==1000 and 'thousands' in o.raw_unit


def test_explicit_cash_flow_period_survives_normalization():
    t=table(['label','Amount'],['For the six months ended June30','RMB thousands'],[None,1000],
        default_currency='CNY',default_unit_scale=1000)
    t.column_periods=[None,'6M2024'];t.rows[0].cells[0]='Net operating cash inflow'
    o=ObservationExtractor()._table_observations(t)[0]
    assert o.period_type=='interim_flow' and o.as_of_date is None
    FinancialNormalizer().normalize_observation(o)
    assert o.period_type=='interim_flow' and o.as_of_date is None
