"""Split table headers support only the exact quoted source row."""

import pytest

from adaptive_document_agent.models import ExtractedTable, TableRow
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.executive_brief import validate_executive_brief, display_brief
from tests.test_executive_brief import result_for, payload


def table_result():
    header = "Six months ended June 30,\n2023 2024\n(USD in thousands)"
    row = "Programme fees .  . . . 1,250 1,475"
    result = result_for([header + "\n" + row])
    result.document.pages[0].tables = [ExtractedTable(
        table_id="fees", page=1, headers=["label", "2023", "2024"],
        column_types=["label", "amount", "amount"],
        column_currencies=[None, "USD", "USD"], column_scales=[None, 1000, 1000],
        rows=[TableRow(cells=["Programme fees", "1,250", "1,475"], page=1, alignment_status="resolved")],
        raw_header_lines=header.splitlines(),
    )]
    brief = ExecutiveBrief.model_validate(payload("Programme fees were USD 1,475 thousand in the six months ended June 30, 2024."))
    brief.items[0].evidence[0].text = "Programme fees . . . 1,250 1,475"
    return result, brief


def test_complete_literal_row_inherits_only_its_explicit_table_headers():
    result, brief = table_result()
    assert not validate_executive_brief(brief, result)


def test_unit_heading_inside_body_can_support_only_its_following_source_row():
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.column_currencies = [None, None, None]
    table.column_scales = [None, None, None]
    table.raw_header_lines = ['Six months ended June 30,', '2023 2024']
    table.rows.insert(0, TableRow(cells=['(USD in thousands)', None, None], page=1))
    assert not validate_executive_brief(brief, result)
    table.rows.reverse()
    assert validate_executive_brief(brief, result)


def test_competing_identical_rows_with_different_scoped_units_are_ambiguous():
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.column_currencies = [None, None, None]
    table.column_scales = [None, None, None]
    table.raw_header_lines = ['Six months ended June 30,', '2023 2024']
    table.rows.insert(0, TableRow(cells=['(USD in thousands)', None, None], page=1))
    other = table.model_copy(deep=True)
    other.table_id = 'different-currency'
    other.rows[0].cells[0] = '(EUR in thousands)'
    result.document.pages[0].text += '\n(EUR in thousands)'
    result.document.pages[0].tables.append(other)
    assert validate_executive_brief(brief, result)


@pytest.mark.parametrize("change", ["currency", "scale", "number", "row", "page", "unresolved", "ambiguous", "date"])
def test_table_context_cannot_authorize_unbound_or_changed_values(change):
    result, brief = table_result()
    if change == "currency": brief.items[0].text = brief.items[0].text.replace("USD", "EUR")
    if change == "scale": brief.items[0].text = brief.items[0].text.replace("thousand", "million")
    if change == "number": brief.items[0].text = brief.items[0].text.replace("1,475", "9,999")
    if change == "row": brief.items[0].evidence[0].text = "1,250 1,475"
    if change == "page": brief.items[0].evidence[0].page = 2
    if change == "unresolved": result.document.pages[0].tables[0].rows[0].alignment_status = "ambiguous"
    if change == "ambiguous":
        other = result.document.pages[0].tables[0].model_copy(deep=True)
        other.table_id = "other-fees"
        other.column_scales = [None, 1_000_000, 1_000_000]
        result.document.pages[0].tables.append(other)
    if change == "date": brief.items[0].text = brief.items[0].text.replace("30", "31")
    assert validate_executive_brief(brief, result)


def test_quote_normalization_does_not_remove_missing_source_words():
    result, brief = table_result()
    result.document.pages[0].text = result.document.pages[0].text.replace("Programme fees", "Programme fees excluding subsidies")
    assert validate_executive_brief(brief, result)


def test_accounting_parentheses_cannot_authorize_positive_amount():
    result, brief = table_result()
    result.document.pages[0].text = "USD in thousands\nNet loss (100) (200)"
    table = result.document.pages[0].tables[0]
    table.rows[0].cells = ["Net loss", "(100)", "(200)"]
    table.raw_header_lines = ["USD in thousands"]
    brief.items[0].evidence[0].text = "Net loss (100) (200)"
    brief.items[0].text = "Net loss was USD 100 thousand."
    assert validate_executive_brief(brief, result)
    brief.items[0].text = "Net loss was USD -100 thousand."
    assert not validate_executive_brief(brief, result)


@pytest.mark.parametrize("text", ["Customer count was 30.", "Fee volume was 2024 units."])
def test_header_date_digits_cannot_authorize_other_body_quantities(text):
    result, brief = table_result()
    brief.items[0].text = text
    assert validate_executive_brief(brief, result)


def test_arbitrary_digits_in_date_header_do_not_authorize_dates_or_body_values():
    result, brief = table_result()
    result.document.pages[0].text += "\nAs of June 30, 2024 999"
    result.document.pages[0].tables[0].raw_header_lines = ["As of June 30, 2024 999", "USD in thousands"]
    brief.items[0].text = "Customer count was 999."
    assert validate_executive_brief(brief, result)
    brief.items[0].text = "Programme fees were USD 1,475 thousand as of June 30, 2024."
    assert validate_executive_brief(brief, result)


def test_same_label_prefix_of_another_table_is_ambiguous():
    result, brief = table_result()
    other = result.document.pages[0].tables[0].model_copy(deep=True)
    other.table_id = "longer-other-table"
    other.rows[0].cells.append("8,000")
    other.column_currencies = [None, "EUR", "EUR", "EUR"]
    other.column_scales = [None, 1e6, 1e6, 1e6]
    result.document.pages[0].tables.append(other)
    result.document.pages[0].text += "\nProgramme fees 1,250 1,475 8,000"
    assert validate_executive_brief(brief, result)


@pytest.mark.parametrize("cell,claim", [("EUR 1,250", "USD 1,250 thousand"),
                                       ("USD 1,250 million", "USD 1,250 thousand")])
def test_explicit_cell_currency_and_scale_cannot_be_replaced_by_column_metadata(cell, claim):
    result, brief = table_result()
    quote = f"Programme fees {cell} 1,475"
    result.document.pages[0].text = "USD in thousands\n" + quote
    result.document.pages[0].tables[0].rows[0].cells[1] = cell
    brief.items[0].evidence[0].text = quote
    brief.items[0].text = "Programme fees were " + claim + "."
    assert validate_executive_brief(brief, result)


@pytest.mark.parametrize("suffix,passes", [(" per day", True), ("/day", True), (" per year", False), ("", False)])
def test_rate_denominator_must_be_retained(suffix, passes):
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.unit_header = table.default_raw_unit = "USD in thousands per day"
    result.document.pages[0].text += "\nUSD in thousands per day"
    brief.items[0].text = f"Programme fees were USD 1,475 thousand{suffix}."
    assert bool(validate_executive_brief(brief, result)) is not passes


@pytest.mark.parametrize("basis,stated,passes", [
    ("employee/day", "employee/day", True),
    ("employee/day", "employee / day", True),
    ("employee/day", "employee/year", False),
    ("employee/day", "employee", False),
    ("full time equivalent employee", "full time equivalent employee", True),
    ("full time equivalent employee", "full year", False),
    ("full time equivalent employee", "full", False),
    ("employee", "employee/day", False),
])
def test_complete_compound_or_multiword_denominator_is_required(basis, stated, passes):
    result, brief = table_result()
    unit = "USD in thousands per " + basis
    table = result.document.pages[0].tables[0]
    table.unit_header = table.default_raw_unit = unit
    result.document.pages[0].text += "\n" + unit
    brief.items[0].text = f"Programme fees were USD 1,475 thousand per {stated}."
    assert bool(validate_executive_brief(brief, result)) is not passes


def test_explicit_column_basis_is_not_contaminated_by_other_header_denominators():
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.headers[2] = "USD in thousands per employee/day"
    table.raw_header_lines += ["USD in thousands per machine/year", "EUR in thousands per full year"]
    result.document.pages[0].text += "\n" + "\n".join([table.headers[2], *table.raw_header_lines[-2:]])
    brief.items[0].text = "Programme fees were USD 1,475 thousand per employee/day."
    assert not validate_executive_brief(brief, result)


def test_unrelated_currency_header_does_not_change_safe_table_unit():
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.raw_header_lines.append("EUR in thousands per hour")
    result.document.pages[0].text += "\nEUR in thousands per hour"
    assert not validate_executive_brief(brief, result)


def test_unit_and_dates_must_be_visible_in_actual_request_excerpt():
    result, brief = table_result()
    excerpt = {1: brief.items[0].evidence[0].text}
    assert validate_executive_brief(brief, result, excerpts=excerpt)
    result.document.pages[0].text = brief.items[0].evidence[0].text
    assert validate_executive_brief(brief, result)


def test_complete_row_requires_ordered_values_not_a_bag_of_numbers():
    result, brief = table_result()
    quote = "Programme fees 1,475 1,250"
    result.document.pages[0].text += "\n" + quote
    brief.items[0].evidence[0].text = quote
    assert validate_executive_brief(brief, result)


def test_multiple_date_groups_cannot_create_unreported_month_year_combinations():
    result, brief = table_result()
    headers = ["Year ended December 31,", "2021 2022", "Six months ended June 30, 2024", "USD in thousands"]
    result.document.pages[0].tables[0].raw_header_lines = headers
    result.document.pages[0].text = "\n".join(headers) + "\n" + brief.items[0].evidence[0].text
    brief.items[0].text = "Programme fees were USD 1,475 thousand as of June 30, 2021."
    assert validate_executive_brief(brief, result)
    brief.items[0].text = "Programme fees were USD 1,475 thousand as of June 30, 2024."
    assert not validate_executive_brief(brief, result)


def test_column_annotation_cannot_supply_an_unlocated_scale_declaration():
    result, brief = table_result()
    result.document.pages[0].tables[0].column_scales = [None, 1_000_000, 1_000_000]
    brief.items[0].text = "Programme fees were USD 1,475 million."
    assert validate_executive_brief(brief, result)


def test_fallback_summary_merges_physical_topic_pages_and_keeps_price_precision():
    from tests.test_pptx_export import _result
    from adaptive_document_agent.models import PresentationPlan, PresentationSlide
    result = _result()
    original = result.charts[0]
    for record in result.observations:
        record.metric_original = record.metric_canonical = "Unit price"
        record.raw_unit = "RMB/unit"
        record.category_dimensions = {"product": "Model Alpha"}
    for record, value in zip(result.observations, [8200, 8100, 8400]):
        record.value = value
        record.raw_value = str(value)
    result.presentation_plan = PresentationPlan(title="Review", slides=[
        PresentationSlide(id=f"part-{i}", slide_type="analysis", title="Unit prices", section_id="prices",
                          section_title="Unit prices", chart_ids=[original.id]) for i in range(2)
    ])
    _, items = display_brief(result)
    assert len(items) == 1
    assert "Model Alpha" in items[0].text
    assert all(number in items[0].text for number in ["8,200", "8,100", "8,400"])

def test_header_extraction_spacing_is_recovered_only_from_literal_source():
    result, brief = table_result()
    result.document.pages[0].tables[0].raw_header_lines = ['SixmonthsendedJune30,', '2023 2024', '(USDinthousands)']
    assert not validate_executive_brief(brief, result)
    result.document.pages[0].tables[0].raw_header_lines[-1] = '(EURinthousands)'
    assert validate_executive_brief(brief, result)


def test_shared_total_does_not_invalidate_an_independent_complete_row():
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.rows.append(TableRow(cells=['Total', '1,250', '1,475'], page=1))
    other = table.model_copy(deep=True)
    other.table_id = 'other-table'
    other.rows = [TableRow(cells=['Other measure', '7', '9'], page=1),
                  TableRow(cells=['Total', '1,250', '1,475'], page=1)]
    other.column_scales = [None, 1_000_000, 1_000_000]
    result.document.pages[0].tables.append(other)
    result.document.pages[0].text += '\nTotal 1,250 1,475\nOther measure 7 9'
    brief.items[0].evidence[0].text += '\nTotal 1,250 1,475'
    assert not validate_executive_brief(brief, result)
    brief.items[0].evidence[0].text = 'Total 1,250 1,475'
    assert validate_executive_brief(brief, result)


def test_rate_keeps_denominator_before_comparison_amount():
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.unit_header = 'USD in thousands per employee/day'
    result.document.pages[0].text += '\n' + table.unit_header
    brief.items[0].text = 'Programme fees rose to USD 1,475 thousand/employee/day from USD 1,250 thousand/employee/day.'
    assert not validate_executive_brief(brief, result)
    brief.items[0].text = brief.items[0].text.replace('/employee/day', '/employee')
    assert validate_executive_brief(brief, result)


def test_concatenated_header_cannot_erase_a_literal_per_unit_denominator():
    result, brief = table_result()
    table = result.document.pages[0].tables[0]
    table.unit_header = table.default_raw_unit = 'USDinthousandsperemployee/day'
    table.raw_header_lines.append(table.unit_header)
    result.document.pages[0].text += '\nUSD in thousands per employee/day'
    brief.items[0].text = 'Programme fees were USD 1,475 thousand.'
    assert validate_executive_brief(brief, result)
    brief.items[0].text = 'Programme fees were USD 1,475 thousand per employee/day.'
    assert not validate_executive_brief(brief, result)


def test_year_row_before_percentage_header_does_not_turn_final_year_into_percent():
    result, brief = table_result()
    quote = '2023 2024\n% of total\nProgramme fees . . . 1,250 1,475'
    result.document.pages[0].text += '\n' + quote
    brief.items[0].evidence[0].text = quote
    brief.items[0].text = 'Programme fees were USD 1,475 thousand in 2024.'
    assert not validate_executive_brief(brief, result)
