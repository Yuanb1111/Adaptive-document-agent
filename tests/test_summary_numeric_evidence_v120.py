"""Footnotes and column-scoped rates keep exact page-bound numerical evidence."""
import pytest

from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for, payload


def percentage_source():
    # No parsed tables: the early introduction must recover its own evidence.
    text = ('Products serve uses such as palletizing.\nYear ended December 31,\n2021 2022 2023\n'
            '% of    % of    % of\n'
            'Amount  Total   Amount  Total   Amount  Total\n'
            '(RMB in thousands, except for percentages)\n'
            'Products . . . 125,957 92.9 104,735 93.5 134,299 95.7\n'
            'Others(1) . . . 12,377 7.1 18,621 6.5 5,146 4.3\n')
    result = result_for([text])
    brief = ExecutiveBrief.model_validate(payload('Others accounted for 7.1%, 6.5% and 4.3%.'))
    brief.items[0].evidence[0].text = text
    return result, brief


def test_attached_footnote_does_not_erase_percentage_column_evidence():
    result, brief = percentage_source()
    before = result.model_dump_json()
    assert not validate_executive_brief(brief, result)
    assert result.model_dump_json() == before


@pytest.mark.parametrize('change', ['amount_as_percent', 'missing_word', 'wrong_order', 'wrong_page'])
def test_footnote_match_cannot_authorize_changed_cells_or_missing_words(change):
    result, brief = percentage_source()
    if change == 'amount_as_percent':
        brief.items[0].text = 'Others accounted for 12,377%.'
    if change == 'missing_word':
        result.document.pages[0].text = result.document.pages[0].text.replace('Others(1)', 'Others excluding services(1)')
    if change == 'wrong_order':
        brief.items[0].evidence[0].text = 'Others(1) . . . 7.1 12,377 6.5 18,621 4.3 5,146'
        result.document.pages[0].text += '\n' + brief.items[0].evidence[0].text
    if change == 'wrong_page':
        brief.items[0].evidence[0].page = 2
    assert validate_executive_brief(brief, result)


def rate_source():
    text = ('Products serve uses such as palletizing.\nYear ended December 31,\n2021 2022 2023\n'
            'Sales           Sales           Sales\n'
            'volume  ASP     volume  ASP     volume  ASP\n'
            '(RMB in thousands/unit for ASP)\n'
            'Alpha . . . 394 65.9 1,707 61.4 2,374 56.6\n'
            'Beta . . . 1,218 13.2 1,560 20.3 960 35.7\n')
    result = result_for([text])
    brief = ExecutiveBrief.model_validate(payload('Alpha ASP fell from RMB65.9 thousand per unit to RMB56.6 thousand per unit.'))
    brief.items[0].evidence[0].text = text
    return result, brief


def test_rate_header_qualifier_is_column_scope_not_part_of_denominator():
    result, brief = rate_source()
    assert not validate_executive_brief(brief, result)
    assert result.document.pages[0].tables == []


@pytest.mark.parametrize('copy', [
    'Alpha ASP was RMB65.9 thousand.',
    'Alpha ASP was RMB65.9 thousand per year.',
    'Alpha ASP was USD65.9 thousand per unit.',
    'Alpha ASP was RMB65.9 million per unit.',
    'Alpha volume was RMB394 thousand per unit.',
])
def test_scoped_rate_header_cannot_lend_currency_scale_or_basis(copy):
    result, brief = rate_source()
    brief.items[0].text = copy
    assert validate_executive_brief(brief, result)


def test_rate_declaration_for_another_column_cannot_qualify_asp():
    result, brief = rate_source()
    result.document.pages[0].text = result.document.pages[0].text.replace('for ASP', 'for volume')
    brief.items[0].evidence[0].text = result.document.pages[0].text
    assert validate_executive_brief(brief, result)


def test_rate_failure_identifies_the_exact_amount_and_source_denominator_for_repair():
    result, brief = rate_source()
    brief.items[0].text = 'Alpha ASP was RMB65.9 thousand.'
    errors = validate_executive_brief(brief, result)
    assert any('RMB65.9 thousand' in error and "source bases=['unit']" in error for error in errors)
