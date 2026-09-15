"""Conservative table reconstruction tests."""

from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.models.table import ExtractedTable, TableRow


def table(page: int, headers: list[str], rows: list[list[str | None]]) -> ExtractedTable:
    return ExtractedTable(
        table_id=f"t{page}",
        page=page,
        headers=headers,
        rows=[TableRow(cells=row, page=page) for row in rows],
        confidence=0.9,
    )


def test_single_cell_section_row_is_preserved_without_fabrication() -> None:
    value = table(1, ["Metric", "2025"], [["Operating", "100"], ["Revenue", None]])
    repaired = TableReconstructor().reconstruct(value)
    assert repaired.rows[0].cells == ["Operating", "100"]
    assert repaired.rows[1].cells == ["Revenue", None]
    assert repaired.confidence == value.confidence


def test_compatible_cross_page_tables_are_combined() -> None:
    first = table(1, ["Metric", "2025"], [["Revenue", "100"]])
    second = table(2, ["Metric", "2025"], [["Profit", "20"]])
    combined = TableReconstructor().combine_continuations([first, second])
    assert len(combined) == 1
    assert len(combined[0].rows) == 2


def test_incompatible_headers_are_not_combined() -> None:
    first = table(1, ["Metric", "2025"], [["Revenue", "100"]])
    second = table(2, ["Region", "Sales"], [["East", "20"]])
    assert len(TableReconstructor().combine_continuations([first, second])) == 2


def test_cross_page_tables_with_different_periods_are_not_combined() -> None:
    first = table(1, ["Metric", "Amount"], [["Revenue", "100"]])
    first.column_periods = [None, "2025"]
    second = table(2, ["Metric", "Amount"], [["Revenue", "90"]])
    second.column_periods = [None, "2024"]
    assert len(TableReconstructor().combine_continuations([first, second])) == 2
