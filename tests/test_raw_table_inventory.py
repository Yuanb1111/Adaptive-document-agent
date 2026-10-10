from adaptive_document_agent.extraction.raw_table_inventory import retain_source_tables
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.models.table import ExtractedTable


def table(identifier, cells, bbox=None):
    return ExtractedTable(table_id=identifier, page=1, raw_cells=cells, bbox=bbox)


def test_raw_inventory_keeps_distinct_tables_with_no_analytical_series():
    first = table('qualitative', [['Terms', 'Description'], ['Security', 'None']])
    second = table('single-period', [['Cost', '125']])
    assert retain_source_tables([first, second]) == [first, second]


def test_physical_duplicate_requires_literal_cells_or_overlapping_subset():
    first = table('first', [['Alpha', '10'], ['Beta', '20']], (10, 10, 80, 50))
    subset = table('partial', [['Beta', '20']], (10, 30, 80, 50))
    other = table('other-page-region', [['Alpha', '10']], (10, 100, 80, 120))
    assert retain_source_tables([subset, first, other]) == [first, other]
    assert retain_source_tables([first, first.model_copy(update={'table_id': 'duplicate'})]) == [first]


def test_single_value_dot_leader_table_and_footnotes_survive():
    class Page:
        text = 'Expense detail\nAs at June 30, 2024\nLease fees(1) . . . . 120\nOther costs . . . . 25\n'
    tables = BorderlessTableExtractor().extract(Page(), 4)
    assert len(tables) == 1
    assert tables[0].raw_cells == [['As at June 30, 2024', None], ['Lease fees(1)', '120'], ['Other costs', '25']]
    assert tables[0].rows[0].cells[0] == 'Lease fees'
    assert tables[0].page == 4


def test_single_numbers_in_prose_are_not_tables():
    class Page:
        text = 'In the year 2024\nWe sold units in 2024\nOur staff count is 140\nMore staff were hired in 2023\n'
    assert not BorderlessTableExtractor().extract(Page(), 1)
    assert BorderlessTableExtractor._parse_row(0, 'Our assets decreased to RMB33.8', minimum_values=1) is None


def test_vertical_periods_remain_visible_in_raw_appendix_cells():
    from tests.test_borderless_table_extraction import VerticalPeriodPage
    table = BorderlessTableExtractor().extract(VerticalPeriodPage(), 1)[0]
    assert ['Year ended December 31, 2022', None, None, None] in table.raw_cells
    assert ['Year ended December 31, 2023', None, None, None] in table.raw_cells
    assert len(table.rows) == 4  # Source header rows never create observations.
