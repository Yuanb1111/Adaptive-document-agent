"""Chinese amount spelling must preserve exactly the same source coefficient."""
import pytest

from adaptive_document_agent.models.executive_brief import BriefQuantityRepresentation
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_brief_table_context import table_result
from tests.test_brief_quantity_representation import magnitude_fixture


def test_chinese_currency_and_thousand_spelling_are_equivalent_without_conversion():
    result, brief = table_result()
    result.document.pages[0].text = result.document.pages[0].text.replace('USD', 'RMB')
    table = result.document.pages[0].tables[0]
    table.column_currencies = [None,'CNY','CNY']
    table.raw_header_lines = [line.replace('USD','RMB') for line in table.raw_header_lines]
    brief.items[0].text = '六个月Programme fees为人民币1,475千元。'
    assert not validate_executive_brief(brief,result)
    for bad in ['人民币1,475百万元', '美元1,475千元', '人民币1,476千元']:
        brief.items[0].text = 'Programme fees为' + bad + '。'
        assert validate_executive_brief(brief,result)


def test_chinese_loss_magnitude_needs_its_exact_signed_item_evidence():
    result, brief = magnitude_fixture()
    brief.items[0].text = '净亏损美元100千元。'
    brief.items[0].quantity_representations = [BriefQuantityRepresentation(
        quantity_text='美元100千元',source_value='-100',representation='absolute_magnitude')]
    assert not validate_executive_brief(brief,result)
    brief.items[0].quantity_representations = []
    assert validate_executive_brief(brief,result)


@pytest.mark.parametrize('text', ['净亏损美元(100千元)。', '净亏损美元(100)千元。'])
def test_chinese_accounting_parentheses_keep_the_source_sign(text):
    result, brief = magnitude_fixture()
    brief.items[0].quantity_representations = []
    brief.items[0].text = text
    assert not validate_executive_brief(brief, result)


@pytest.mark.parametrize('text', ['人民币20.6百万元', '人民币20.6 million'])
def test_chinese_million_spelling_preserves_literal_source_scale(text):
    from tests.test_executive_brief import result_for,payload
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief
    result=result_for(['Cash burn was RMB20.6 million.'])
    brief=ExecutiveBrief.model_validate(payload(text))
    brief.items[0].evidence[0].text='Cash burn was RMB20.6 million.'
    assert not validate_executive_brief(brief,result)


def test_early_reading_recovers_literal_table_units_without_observations_or_mutation():
    result,brief=table_result()
    # Preserve explicit fixed-layout headers/rows, as supplied at ingestion.
    result.document.pages[0].text=('Year ended December 31\n2023      2024\n'
        '(USD in thousands)\nProgramme fees       1,250     1,475\n'
        'Other fees             50        70')
    result.document.pages[0].tables=[]
    result.observations=[]
    brief.items[0].evidence[0].text=result.document.pages[0].text
    brief.items[0].text='Programme fees were USD 1,475 thousand in 2024.'
    before=result.model_dump()
    assert not validate_executive_brief(brief,result)
    assert result.model_dump()==before
    brief.items[0].text='Programme fees were EUR 1,475 thousand in 2024.'
    assert validate_executive_brief(brief,result)


def test_chinese_calendar_date_requires_the_exact_bound_header_date():
    result, brief = table_result()
    brief.items[0].text = '截至2024年6月30日，Programme fees为美元1,475千元。'
    assert not validate_executive_brief(brief, result)
    brief.items[0].text = '截至2024年6月31日，Programme fees为美元1,475千元。'
    assert validate_executive_brief(brief, result)


def test_attached_table_leaders_do_not_hide_a_complete_source_row():
    result, brief = table_result()
    result.document.pages[0].text = result.document.pages[0].text.replace(
        'Programme fees .  . . .', 'Programme fees. . . . .')
    brief.items[0].evidence[0].text = 'Programme fees. . . . . 1,250 1,475'
    assert not validate_executive_brief(brief, result)
    from adaptive_document_agent.services.source_quotes import normalize_quote
    assert normalize_quote('Ratio 1.25 and 3..5') == 'ratio 1.25 and 3..5'
