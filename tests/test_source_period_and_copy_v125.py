import pytest

from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.models.table import ExtractedTable, TableRow


@pytest.mark.parametrize('stock', [False, True])
def test_literal_duration_header_outranks_metric_keyword_but_not_explicit_stock(stock):
    table = ExtractedTable(table_id='cash-source', page=1, headers=['Metric', '6M2022', '6M2023'],
        column_periods=[None, '6M2022', '6M2023'],
        raw_header_lines=['As of 6M2022 6M2023' if stock else 'FY2021 6M2022 6M2023', 'RMB’000 RMB’000'],
        rows=[TableRow(page=1,cells=['Net cash used in activities', '(115)', '(526)'])],
        default_unit='currency',default_raw_unit='RMB’000',default_currency='RMB',default_unit_scale=1000,confidence=.9)
    observations=ObservationExtractor()._table_observations(table)
    assert len(observations)==2
    assert all(o.period_type == ('balance_sheet_date' if stock else 'interim_flow') for o in observations)
    if not stock:
        assert all(o.as_of_date is None for o in observations)
    assert [o.raw_value for o in observations]==['(115)','(526)']


def test_duplicate_copy_reconciliation_is_local_exact_and_keeps_evidence():
    from adaptive_document_agent.agent.summary_draft_duplicates import deduplicate_draft
    from tests.test_summary_content_repair_v122 import draft
    original=draft()
    original.pages[1].items.append(original.pages[1].items[0].model_copy(update={'label':'Repeated label'}))
    original.pages[1].items.append(original.pages[1].items[0].model_copy(update={'fact_ids':['different-fact']}))
    original.pages[1].items.append(original.pages[1].items[0].model_copy(update={'text':'Different copy.'}))
    audit={}
    revised=deduplicate_draft(original,audit)
    assert len(original.pages[1].items)==4
    assert len(revised.pages[1].items)==3
    assert revised.pages[0]==original.pages[0]
    assert {fid for i in revised.pages[1].items for fid in i.fact_ids}=={'f2','different-fact'}
    assert audit['identical_copy_reconciliation'][0]['original_item']['label']=='Repeated label'
