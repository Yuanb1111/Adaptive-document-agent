"""Repeated record headers retain independent dates, units and calendar fields."""

from copy import deepcopy

import pymupdf
import pytest

from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.source_table_audit import page_inventory_errors
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.models import DocumentPage
from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.validation import ExtractionValidator


def record_tables_pdf(dimension, *, period_above=False, wide_label=False):
    document = pymupdf.open()
    page = document.new_page(width=650, height=700)
    # Page furniture encloses both tables, as in source documents without a
    # closing rule between the two independent record blocks.
    for y in (40, 65):
        page.draw_line((40, y), (610, y))
    page.insert_text((250, 55), "ACTIVITY REPORT", fontsize=10)
    amount_x, share_x, year_x = (300, 400, 520) if wide_label else (200, 320, 450)
    for top, year, unit, values in (
        (120, "2024", "USD thousands", [("Alpha", "120", "60", "2018"), ("Beta", "80", "40", "2019")]),
        (360, "2025", "EUR millions", [("Alpha", "9", "30", "2018"), ("Beta", "21", "70", "2019")]),
    ):
        for x, text in ((amount_x, "Reported"), (share_x, "Share"), (year_x, "Year of")):
            page.insert_text((x, top), text, fontsize=9)
        for x, text in ((40, "Record"), (amount_x, "amount"), (share_x, "(%)"), (year_x, dimension)):
            page.insert_text((x, top + 15), text, fontsize=9)
        page.insert_text((amount_x, top + 30), unit, fontsize=9)
        page.insert_text((40, top - 20 if period_above else top + 50),
                         f"For the year ended December 31, {year}", fontsize=9)
        for index, row in enumerate(values):
            for x, text in zip((40, amount_x, share_x, year_x), row):
                page.insert_text((x, top + 75 + index * 20), text, fontsize=9)
    raw = document.tobytes()
    document.close()
    return raw


@pytest.mark.parametrize("dimension", ["installation", "registration", "enrolment"])
@pytest.mark.parametrize("period_above", [False, True])
@pytest.mark.parametrize("wide_label", [False, True])
def test_repeated_source_headers_separate_periods_units_and_numeric_dimensions(dimension, period_above, wide_label):
    extractor = TableExtractor()
    tables = extractor.extract(record_tables_pdf(dimension, period_above=period_above, wide_label=wide_label))[1]
    assert not extractor.page_errors
    assert len(tables) == 2
    literal = extractor.raw_tables_by_page[1]
    assert len(literal) == 2
    for table, year in zip(literal, ("2024", "2025")):
        assert any(f"For the year ended December 31, {year}" == line for line in table.raw_header_lines)
        assert not any("For the year ended" in line for line in table.raw_body_lines)
    retained = deepcopy([table.model_dump() for table in literal])
    observations = [item for table in tables for item in ObservationExtractor()._table_observations(table)]
    assert len(observations) == 8
    assert {item.period for item in observations} == {"FY2024", "FY2025"}
    assert not [issue for issue in ExtractionValidator().validate(observations).issues
                if issue.code == "conflicting_values"]
    for item in observations:
        assert item.raw_value not in {"2018", "2019"}
        assert item.dimensions[f"Year of {dimension}"] in {"2018", "2019"}
        assert item.evidence[0].page == 1
        assert item.evidence[0].table_id in {table.table_id for table in literal}
    amounts = [item for item in observations if item.unit == "currency"]
    assert [(item.raw_value, item.value, item.currency) for item in amounts] == [
        ("120", 120_000, "USD"), ("80", 80_000, "USD"),
        ("9", 9_000_000, "EUR"), ("21", 21_000_000, "EUR"),
    ]
    assert [table.model_dump() for table in literal] == retained
    page = DocumentPage(page_number=1, raw_tables=literal,
                        source_table_inventory=extractor.source_inventory_by_page[1])
    assert not page_inventory_errors(page)


@pytest.mark.parametrize("dimension", ["Year of manufacture", "Registration year", "Date of approval"])
def test_record_calendar_field_cannot_inherit_a_neighboring_currency(dimension):
    source = ExtractedTable(table_id="records", page=4, confidence=.9,
        raw_header_cells=[["Record", "Purchase amount", "Percentage", dimension],
                          ["", "GBP thousands", "%", ""],
                          ["For the year", "ended December", "31, 2025", ""]],
        raw_header_lines=["Record Purchase amount Percentage " + dimension,
                          "GBP thousands %", "For the year ended December 31, 2025"],
        raw_cells=[["Alpha", "100", "25", "2020"], ["Beta", "300", "75", "2021"]])
    before = source.model_dump()
    analytical = TableExtractor()._analytical_copy(source)
    observations = ObservationExtractor()._table_observations(analytical)
    assert len(observations) == 4
    assert all(item.period == "FY2025" for item in observations)
    assert all(item.dimensions[dimension] in {"2020", "2021"} for item in observations)
    assert {item.value for item in observations} == {100_000, 300_000, 25, 75}
    assert source.model_dump() == before


def test_record_date_caption_is_not_a_shared_period_without_explicit_reporting_syntax():
    source = ExtractedTable(table_id="records", page=4, confidence=.9,
        raw_header_cells=[["Supplier survey completed in 2025", "", ""],
                          ["Record", "Purchase amount", "Year of manufacture"]],
        raw_cells=[["Alpha", "100", "2020"], ["Beta", "300", "2021"]])
    analytical = TableExtractor()._analytical_copy(source)
    assert analytical.column_periods == [None, None, None]
    observations = ObservationExtractor()._table_observations(analytical)
    assert len(observations) == 2
    assert all(item.period is None and item.unit != "currency" for item in observations)


@pytest.mark.parametrize("heading,unit", [
    ("Revenue per year", "USD"),
    ("Revenue per year (USD)", ""),
    ("Annual production last year", "units"),
    ("Registration year (USD)", ""),
])
def test_measure_units_and_time_qualifiers_do_not_become_calendar_dimensions(heading, unit):
    source = ExtractedTable(table_id="measure", page=4, confidence=.9,
        raw_header_cells=[["Record", heading], ["", unit]],
        raw_cells=[["Alpha", "2020"], ["Beta", "2021"]])
    analytical = TableExtractor()._analytical_copy(source)
    assert analytical.column_types[1] != "dimension"
    observations = ObservationExtractor()._table_observations(analytical)
    assert len(observations) == 2
    assert {item.raw_value for item in observations} == {"2020", "2021"}
    assert not any(heading in item.dimensions for item in observations)


def test_ordinal_service_year_is_not_inferred_to_be_a_calendar_year():
    source = ExtractedTable(table_id="duration", page=4, confidence=.9,
        raw_header_cells=[["Record", "Year of service"]],
        raw_cells=[["Alpha", "1"], ["Beta", "2"]])
    analytical = TableExtractor()._analytical_copy(source)
    assert analytical.column_types[1] != "dimension"


def test_table_date_does_not_overwrite_explicit_column_dates():
    rows = [["", "As of June 30, 2024", ""],
            ["Metric", "2024-06-30", "2023-12-31"],
            ["Samples", "20", "10"]]
    _, periods, *_ = TableReconstructor.reconstruct_multi_tier_headers(rows, header_row_count=2)
    assert periods == [None, "2024-06-30", "2023-12-31"]


def test_table_date_does_not_overwrite_existing_periods_or_fill_conflicting_gaps():
    rows = [["For the year ended December 31, 2024", "", "", ""],
            ["Record", "Amount", "Percentage", "Quantity"],
            ["Alpha", "20", "10", "30"]]
    _, periods, *_ = TableReconstructor.reconstruct_multi_tier_headers(
        rows, header_row_count=2, existing_periods=[None, "FY2024", "FY2023", None])
    assert periods == [None, "FY2024", "FY2023", None]


def test_consistent_table_reporting_date_can_fill_missing_record_field_periods():
    rows = [["For the year ended December 31, 2024", "", ""],
            ["Record", "Amount", "Percentage"],
            ["Alpha", "20", "10"]]
    _, periods, *_ = TableReconstructor.reconstruct_multi_tier_headers(
        rows, header_row_count=2, existing_periods=[None, "FY2024", None])
    assert periods == [None, "FY2024", "FY2024"]
