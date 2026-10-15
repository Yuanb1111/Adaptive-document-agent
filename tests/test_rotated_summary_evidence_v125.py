import pymupdf
import pytest

from adaptive_document_agent.extraction.pdf_parser import PDFParser
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_summary_source_failures_v125 import brief_for


def literal_table():
    return ExtractedTable(table_id='literal', page=1,
        raw_header_cells=[['', 'FY2022', '', 'FY2023', ''],
            ['', '', 'Gross', '', 'Gross'], ['', 'Gross', 'profit', 'Gross', 'profit'],
            ['', 'profit', '/(loss)', 'profit', '/(loss)'],
            ['', '/(loss)', 'margin', '/(loss)', 'margin'],
            ['', "RMB'000", '%', "RMB'000", '%'], ['', '', '', '(unaudited)', '']],
        raw_header_lines=["FY2022 FY2023", "RMB'000 % RMB'000 %"],
        raw_header_spans=[(0,1,2),(0,3,4)],
        raw_cells=[['Total', '310', '41.2', '520', '32.4']])


def test_known_geometry_header_count_preserves_deep_percentage_tiers():
    raw = literal_table()
    analytical = TableExtractor()._analytical_copy(raw)
    assert analytical.column_types == ['label', 'amount', 'percentage', 'amount', 'percentage']
    assert analytical.column_currencies == [None, 'CNY', None, 'CNY', None]
    assert analytical.column_scales == [None, 1000, 1, 1000, 1]
    assert raw.raw_cells == [['Total', '310', '41.2', '520', '32.4']]
    assert analytical.raw_header_cells == raw.raw_header_cells


@pytest.mark.parametrize('rotation', [90, 180, 270])
def test_rotated_reading_retains_source_and_separates_amount_from_percentage(rotation):
    source = pymupdf.open()
    page = source.new_page(width=600, height=300)
    page.insert_text((40, 40), 'FY2022 FY2023')
    page.insert_text((40, 65), "RMB'000 % RMB'000 %")
    page.insert_text((40, 90), 'Total 310 41.2 520 32.4')
    document = pymupdf.open()
    target = document.new_page(width=700, height=700)
    target.show_pdf_page(target.rect, source, 0, rotate=rotation)
    target.insert_text((20, 690), 'Unrotated footer')
    raw = target.get_text('text', sort=True)
    parsed = PDFParser().parse(document.tobytes(), extract_tables=False).pages[0]
    assert parsed.raw_text == raw
    assert parsed.reading_rotation != 0
    assert 'Total 310 41.2 520 32.4' in parsed.text
    assert 'Unrotated footer' in parsed.text
    parsed.tables = [TableExtractor()._analytical_copy(literal_table())]
    result, brief = brief_for(parsed.text, 'Total gross profit: RMB310 thousand; margin: 41.2%.')
    result.document.pages = [parsed]
    assert not validate_executive_brief(brief, result)
    for invalid in ['Total gross profit: RMB41.2 thousand.', 'Total margin: 310%.',
                    'Total gross profit: USD310 thousand.', 'Total gross profit: RMB310 million.']:
        brief.items[0].text = invalid
        assert validate_executive_brief(brief, result)
    brief.items[0].text = 'Total gross profit: RMB310 thousand.'
    brief.items[0].evidence[0].text = '310'
    assert validate_executive_brief(brief, result)
    source.close()
    document.close()
