import pytest

from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for, payload


def brief_for(source, claim):
    result = result_for([source])
    brief = ExecutiveBrief.model_validate(payload(claim))
    brief.items[0].evidence[0].text = source
    return result, brief


def test_signed_cell_does_not_erase_a_separately_cited_explicit_percentage():
    source = ("FY2022 FY2023\nRMB’000 RMB’000\nNet result (6.6) (7.7)\n"
              "The company reported a gross loss margin of 6.6%.")
    result, brief = brief_for(source, 'The company reported a gross loss margin of 6.6%.')
    assert not validate_executive_brief(brief, result)
    brief.items[0].text = 'Net result was RMB6.6 thousand.'
    assert validate_executive_brief(brief, result)
    brief.items[0].text = 'The margin was 6.6%.'
    brief.items[0].evidence[0].text = source.split('The company')[0].rstrip()
    assert validate_executive_brief(brief, result)


def test_explicit_positive_amount_keeps_its_own_unit_beside_negative_table_cell():
    source = ("FY2022 FY2023\nRMB’000 RMB’000\nNet result (14) (25)\n"
              "A separate contract was RMB14 million.")
    result, brief = brief_for(source, 'The contract was RMB14 million.')
    assert not validate_executive_brief(brief, result)
    for text in ['Net result was RMB14 thousand.', 'The contract was USD14 million.']:
        brief.items[0].text = text
        assert validate_executive_brief(brief, result)


def test_translated_month_year_is_supported_only_as_the_exact_cited_date():
    source = 'Transactions occurred in September 2024, December 2024, July 2025 and October 2025.'
    result, brief = brief_for(source, '交易发生于2024年9月、2024年12月、2025年7月及2025年10月。')
    assert not validate_executive_brief(brief, result)
    for text in ['交易发生于2024年7月。', '客户共有9名。', '交易发生于2025年10月9日。']:
        brief.items[0].text = text
        assert validate_executive_brief(brief, result)


def wrapped_amount():
    source = 'HK$9,945.6\nMarket capitalization(1)        million'
    result, brief = brief_for(source, 'Market capitalization is HK$9,945.6 million.')
    result.document.pages[0].text_blocks = [
        dict(text='HK$9,945.6', bbox=[470, 470, 525, 480]),
        dict(text='Market capitalization(1)', bbox=[90, 478, 430, 490]),
        dict(text='million\nNext label', bbox=[90, 480, 525, 500], lines=[
            dict(text='million', bbox=[490, 480, 525, 490]),
            dict(text='Next label', bbox=[90, 491, 420, 500])])]
    return result, brief


def test_percentage_row_unit_does_not_depend_on_year_column_unit():
    source = ('Key ratios\n2020 2021 2022 2023\n'
              'Gross profit margin(1) (%) 44.7 31.3 29.2 20.2\n'
              'Current ratio(2) (times) 1.2 1.0 1.0 1.4\n'
              'Gearing ratio(4) (%) 65.8 111.2 65.4 62.4')
    result, brief = brief_for(source, 'Gross profit margins: 44.7%, 31.3%, 29.2%, 20.2%; gearing: 65.8%, 111.2%, 65.4%, 62.4%.')
    assert not validate_executive_brief(brief, result)
    brief.items[0].evidence[0].text = ' '.join(source.split())
    assert not validate_executive_brief(brief, result)
    for text in ['Current ratio is 1.2%.', 'Gross profit margin is 45.7%.']:
        brief.items[0].text = text
        assert validate_executive_brief(brief, result)
    brief.items[0].text = 'Gross profit margin is 44.7%.'
    brief.items[0].evidence[0].text = '44.7 31.3 29.2 20.2'
    assert validate_executive_brief(brief, result)


def test_wrapped_scale_uses_line_geometry_without_changing_source():
    result, brief = wrapped_amount()
    before = result.model_dump()
    assert not validate_executive_brief(brief, result)
    assert result.model_dump() == before


def test_uniform_literal_currency_header_preserves_signs_without_parsed_grid():
    source = "FY2022 FY2023 FY2024\nRMB’000 RMB’000 RMB’000\nNet result (121) (142) (163)\nExpenses 14 25 36"
    result, brief = brief_for(source, 'Net result was RMB-121 thousand; expenses were RMB14 thousand.')
    assert not validate_executive_brief(brief, result)
    brief.items[0].text = 'Net result was negative RMB121 thousand; expenses were RMB14 thousand.'
    assert not validate_executive_brief(brief, result)
    for text in ['Net result was RMB121 thousand.', 'Net result was non-negative RMB121 thousand.', 'Expenses were USD14 thousand.',
                 'Expenses were RMB14 million.']:
        brief.items[0].text = text
        assert validate_executive_brief(brief, result)
    brief.items[0].text = 'Expenses were RMB14 thousand.'
    brief.items[0].evidence[0].text = 'Expenses 14 25 36'
    from adaptive_document_agent.services.brief_literal_table_units import uniform_quoted_rows
    assert not uniform_quoted_rows(source, brief.items[0].evidence[0].text)


def test_rounded_signed_amount_is_rejected_with_exact_source_repair_hint():
    from adaptive_document_agent.services.brief_quantity_representation import source_native_quantity_hint
    source = "RMB’000 RMB’000\nAdjusted net result (642,509) (761,123)"
    result, brief = brief_for(source, 'Adjusted net result was RMB642.5 million.')
    errors = validate_executive_brief(brief, result)
    assert any('rmb -642509 thousand' in error for error in errors)
    assert source_native_quantity_hint('usd', '642.5', 'million', {('rmb','-642509','thousand')}) is None
    assert source_native_quantity_hint('rmb', '642.5', 'million', {
        ('rmb','-642509','thousand'), ('rmb','642510','thousand')}) is None
    brief.items[0].text = 'Adjusted net result was RMB-642,509 thousand.'
    assert not validate_executive_brief(brief,result)


@pytest.mark.parametrize('source', [
    "RMB’000 USD’000 RMB’000\nExpenses 14 25 36",
    "RMB’000 RMB’000 RMB’000\nExpenses 14 25",
    "RMB’000 RMB’000 RMB’000\nExpenses 14 25 36 47",
    "RMB’000 RMB’000 RMB’000\nOther subject.\nExpenses 14 25 36",
    "RMB’000 RMB’000 RMB’000\nRate (%) 14 25 36",
    "RMB’000 RMB’000 RMB’000\n% % %\nRate 14 25 36",
    "RMB’000 RMB’000 RMB’000\nFY2022 FY2023 FY2024\nExpenses 14 25 36",
])
def test_literal_unit_recovery_cannot_borrow_mixed_incomplete_or_unrelated_header(source):
    from adaptive_document_agent.services.brief_literal_table_units import uniform_quoted_rows
    assert not uniform_quoted_rows(source, source)


@pytest.mark.parametrize('change', ['currency', 'scale', 'uncited', 'unaligned', 'ambiguous', 'no_geometry'])
def test_wrapped_scale_cannot_borrow_unrelated_or_ambiguous_units(change):
    result, brief = wrapped_amount()
    blocks = result.document.pages[0].text_blocks
    if change == 'currency': brief.items[0].text = brief.items[0].text.replace('HK$', 'RMB')
    if change == 'scale': brief.items[0].text = brief.items[0].text.replace('million', 'billion')
    if change == 'uncited': brief.items[0].evidence[0].text = 'HK$9,945.6\nMarket capitalization(1)'
    if change == 'unaligned': blocks[2]['lines'][0]['bbox'] = [100, 480, 135, 490]
    if change == 'ambiguous': blocks.append(dict(text='USD8,000', bbox=[470, 470, 525, 480]))
    if change == 'no_geometry': blocks[2].pop('lines')
    assert validate_executive_brief(brief, result)


def test_unbudgeted_theme_can_use_addressed_repair_without_rewriting_other_items():
    from adaptive_document_agent.agent.compact_summary import CompactSummaryDraft
    from adaptive_document_agent.agent.summary_content_repair import revise_content
    original = CompactSummaryDraft(pages=[dict(title='Scope', items=[
        dict(label='Accepted', text='Accepted statement.', fact_ids=['f0']),
        dict(label='Wrong', text='Unsupported statement.', fact_ids=['f1'])])])
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            return schema(replacements=[dict(item_id='g0_i1', replacement=dict(
                label='Corrected', text='Supported statement.', fact_ids=['f2']))])
    revised = revise_content(Gateway(), original, [], CompactSummaryDraft, {}, errors=['Wrong: unsupported.'])
    assert revised.pages[0].items[0] == original.pages[0].items[0]
    assert revised.pages[0].items[1].fact_ids == ['f2']


def test_theme_source_rejection_routes_to_targeted_patch_then_full_review():
    from tests.test_compact_summary_v111 import fixture, Reviewer
    from adaptive_document_agent.agent.compact_summary import generate_compact_summary
    from adaptive_document_agent.models import CompanyProfile
    result, review, valid = fixture()
    from copy import deepcopy
    invalid = deepcopy(valid)
    invalid['pages'][0]['items'][0]['text'] = 'Revenue was RMB999 million.'
    class RecoveringReviewer(Reviewer):
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'SummarySynthesisRevision':
                self.calls.append(schema.__name__)
                return schema(replacements=[dict(item_id='g0_i0', replacement=valid['pages'][0]['items'][0])])
            return super().generate_structured(messages, schema, **kwargs)
    client = RecoveringReviewer(invalid)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.calls == ['CompactSummaryDraft', 'SummarySynthesisRevision', 'CompactSummaryReview']
    assert all('999' not in item.text for page in company.summary_pages for item in page.items)
    assert review.plan_audits[1]['addressed_content_revision']['replacements'][0]['item_id'] == 'g0_i0'
