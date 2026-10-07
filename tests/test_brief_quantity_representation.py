"""Magnitude wording is explicit and bound to signed item-local evidence."""
import pytest
from adaptive_document_agent.models.executive_brief import BriefQuantityRepresentation
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_brief_table_context import table_result


def magnitude_fixture():
    result, brief = table_result()
    result.document.pages[0].text = 'USD in thousands\nNet loss (100) (200)'
    table = result.document.pages[0].tables[0]
    table.rows[0].cells = ['Net loss', '(100)', '(200)']
    table.raw_header_lines = ['USD in thousands']
    brief.items[0].evidence[0].text = 'Net loss (100) (200)'
    brief.items[0].text = 'Net loss was USD 100 thousand.'
    brief.items[0].quantity_representations = [BriefQuantityRepresentation(
        quantity_text='USD 100 thousand', source_value='-100', representation='absolute_magnitude')]
    return result, brief


def test_explicit_magnitude_retains_source_sign_and_display_copy():
    result, brief = magnitude_fixture()
    before = result.model_dump(), brief.model_dump()
    assert not validate_executive_brief(brief, result)
    assert (result.model_dump(), brief.model_dump()) == before


@pytest.mark.parametrize('fault', ['currency', 'scale', 'value', 'sign', 'source', 'missing', 'duplicate', 'other_item'])
def test_invalid_magnitude_binding_cannot_bypass_numeric_checks(fault):
    result, brief = magnitude_fixture()
    item = brief.items[0]
    binding = item.quantity_representations[0]
    if fault == 'currency': item.text = item.text.replace('USD', 'EUR'); binding.quantity_text = 'EUR 100 thousand'
    if fault == 'scale': item.text = item.text.replace('thousand', 'million'); binding.quantity_text = 'USD 100 million'
    if fault == 'value': item.text = item.text.replace('100', '101'); binding.quantity_text = 'USD 101 thousand'
    if fault == 'sign': binding.source_value = '100'
    if fault == 'source': binding.source_value = '-101'
    if fault == 'missing': item.quantity_representations = []
    if fault == 'duplicate': item.text += ' USD 100 thousand.'
    if fault == 'other_item': item.evidence[0].text = 'Unrelated amount was USD 20 thousand.'; result.document.pages[0].text += '\n' + item.evidence[0].text
    assert validate_executive_brief(brief, result)


def test_magnitude_binding_still_requires_exact_rate_denominator():
    result, brief = magnitude_fixture()
    table = result.document.pages[0].tables[0]
    table.unit_header = 'USD in thousands per employee/day'
    result.document.pages[0].text += '\n' + table.unit_header
    assert validate_executive_brief(brief, result)
    brief.items[0].text = 'Net loss was USD 100 thousand per employee/day.'
    assert not validate_executive_brief(brief, result)
