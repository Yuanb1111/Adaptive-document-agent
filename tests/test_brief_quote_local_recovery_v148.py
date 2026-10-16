"""A header fragment cannot erase complete literal evidence; real ambiguity still blocks."""
from copy import deepcopy
import pytest
from adaptive_document_agent.models import ExtractedTable, TableRow
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for

SOURCE = """Year ended December 31,
2022 2023 2024
% of % of % of
Amount revenue Amount revenue Amount revenue
(USD in thousands, except for percentages)
Programme fees 120,000 100.0 150,000 100.0 180,000 100.0
Service costs (80,000) (66.7) (100,000) (66.7) (120,000) (66.7)
Operating surplus 40,000 33.3 50,000 33.3 60,000 33.3"""


def case():
    result = result_for([SOURCE])
    brief = ExecutiveBrief(items=[ExecutiveBriefItem(label='Programme fees',
        text='Programme fees were USD120,000 thousand in 2022, representing 100.0% of revenue.',
        evidence=[BriefQuote(page=1,text=SOURCE)])])
    fragment=ExtractedTable(table_id='header-fragment',page=1,
        headers=['label','2022 Amount','2023 Amount','2024 Amount'],
        column_types=['label','amount','amount','amount'],
        column_currencies=[None,'USD','USD','USD'],column_scales=[None,1000,1000,1000],
        raw_header_lines=['2022 2023 2024'],rows=[
            TableRow(cells=['Amount','revenue','Amount revenue','Amount revenue'],page=1,alignment_status='resolved'),
            TableRow(cells=['','2022','2023','2024'],page=1,alignment_status='resolved')])
    return result,brief,fragment


def test_parsed_header_fragment_cannot_remove_unchanged_complete_quote_support():
    result,brief,fragment=case()
    assert not validate_executive_brief(brief,result)
    result.document.pages[0].tables=[fragment]
    result.document.pages[0].raw_tables=[fragment.model_copy(deep=True)]
    before=result.model_dump_json()
    assert not validate_executive_brief(brief,result)
    assert result.model_dump_json()==before


@pytest.mark.parametrize('fault',['partial_same_label','wrong_currency','wrong_scale','wrong_column_roles','unresolved_same_label','placeholder_same_label'])
def test_literal_recovery_does_not_override_existing_row_ownership_or_conflicts(fault):
    result,brief,fragment=case()
    from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
    table=next(t for t in BorderlessTableExtractor().extract(result.document.pages[0],1)
               if any(r.cells[0]=='Programme fees' for r in t.rows))
    complete=table.model_copy(deep=True)
    complete.table_id='complete-source-grid'
    table.table_id='existing-source-grid'
    if fault=='partial_same_label':table.rows[0].cells=table.rows[0].cells[:3]
    elif fault=='wrong_currency':table.column_currencies=[None]+['EUR']*6
    elif fault=='wrong_scale':table.column_scales=[None]+[1000000]*6
    elif fault=='wrong_column_roles':table.column_types=['label']+['percentage']*6
    elif fault=='unresolved_same_label':table.rows[0].alignment_status='ambiguous'
    else:table.rows=[TableRow(cells=['Programme fees',None,None],page=1)]
    result.document.pages[0].tables=[fragment,table]+([complete] if fault=='partial_same_label' else [])
    assert validate_executive_brief(brief,result)


@pytest.mark.parametrize('fault',['partial_row','unquoted_headers','unquoted_units','wrong_amount','wrong_currency','wrong_scale','percentage_as_amount'])
def test_new_literal_support_requires_complete_quoted_columns_and_unchanged_units(fault):
    result,brief,fragment=case()
    result.document.pages[0].tables=[fragment]
    item=brief.items[0]
    if fault=='partial_row':item.evidence[0].text=SOURCE.split('Programme fees')[0]+'Programme fees 120,000 100.0'
    elif fault=='unquoted_headers':item.evidence[0].text=SOURCE.split('Programme fees',1)[1];item.evidence[0].text='Programme fees'+item.evidence[0].text
    elif fault=='unquoted_units':item.evidence[0].text=SOURCE.replace('(USD in thousands, except for percentages)\n','')
    elif fault=='wrong_amount':item.text=item.text.replace('120,000','121,000')
    elif fault=='wrong_currency':item.text=item.text.replace('USD','EUR')
    elif fault=='wrong_scale':item.text=item.text.replace('thousand','million')
    else:item.text='Programme fees were USD100 thousand in 2022.'
    assert validate_executive_brief(brief,result)
