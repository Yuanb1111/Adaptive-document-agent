"""Spare standalone-table space improves type without creating continuations."""
import pytest

from adaptive_document_agent.services.table_typography import exact_table_layout


@pytest.mark.parametrize('height,size', [(3.7,18), (3.3,16), (3.0,14), (2.0,14)])
def test_largest_complete_table_size_is_selected_before_pagination(height, size):
    rows = [('Reported measure', 'FY2023', '29.3%')] * 6
    actual, wrapped, heights = exact_table_layout(rows, (5.0, 2.0, 3.0), height, enlarge=True)
    assert actual == size and wrapped == rows
    assert len(heights) == 7
    if size > 14:
        assert sum(heights) <= height


def test_support_table_and_multiline_cells_keep_complete_copy():
    label = 'Complete source qualification ' * 12
    cells = [(label, '31 December 2023 (unaudited)', '(1,234.56)')]
    size, wrapped, heights = exact_table_layout(cells, (3.0, 2.0, 2.0), 20, enlarge=False)
    assert size == 14 and heights[1] > .4
    assert [''.join(v.split()) for v in wrapped[0]] == [''.join(v.split()) for v in cells[0]]


@pytest.mark.parametrize('count,expected_sizes,expected_pages', [(6,{18},1), (13,{14},2)])
def test_native_table_font_is_consistent_and_never_adds_pages(count, expected_sizes, expected_pages):
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.models import PresentationSlide, PresentationVisualBlock
    from adaptive_document_agent.services.slide_compositor import render_composed_slide, validate_composed_geometry
    from tests.test_p0_composition import observation, result_for
    from tests.test_presentation_brief import blank_deck
    records = [observation(f'fact-{i:02}', f'Measure {i:02}', i + 10, None) for i in range(count)]
    plan = PresentationSlide(id='table', slide_type='analysis', title='Reported measurements',
        layout='data_overview', source_pages=[3], visual_blocks=[
            PresentationVisualBlock(role='table', observation_ids=[o.id for o in records])])
    result = result_for(records, [], plan)
    before = result.model_dump_json()
    deck = blank_deck()
    pages = render_composed_slide(deck, plan, [], result, DocumentIndex(records))
    tables = [s for page in pages for s in page.shapes if s.has_table]
    assert len(pages) == len(tables) == expected_pages
    assert {p.font.size.pt for s in tables for r in s.table.rows for c in r.cells
            for p in c.text_frame.paragraphs} == expected_sizes
    assert [oid for s in tables for oid in s.name.removeprefix('table:').split(',')] == [o.id for o in records]
    assert all(s.table.cell(0, 0).text == 'Metric' for s in tables)
    assert all(s.table.cell(r, 1).text == 'Unspecified' for s in tables for r in range(1,len(s.table.rows)))
    assert result.model_dump_json() == before
    validate_composed_geometry(deck)
