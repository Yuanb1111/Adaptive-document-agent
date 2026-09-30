"""Matrix continuation retains complete, readable rows and their evidence."""

import json

import pytest

from adaptive_document_agent.models import Observation, PresentationSlide, PresentationVisualBlock, SourceEvidence
from adaptive_document_agent.services.presentation_matrix import comparison_matrix, render_matrix
from adaptive_document_agent.services.slide_compositor import _lines
from tests.test_presentation_brief import blank_deck


def _matrix(*, row_count=6, column_count=3, labels=None, raw_values=None):
    observations = []
    labels = labels or [f"Category {row + 1}" for row in range(row_count)]
    for row, label in enumerate(labels):
        for column in range(column_count):
            value = (row + 1) * 10 + column + .5
            raw_value = raw_values[row] if raw_values else f"{value:.1f}"
            observations.append(Observation(
                id=f"cell-{row}-{column}", metric_original=f"Measure {column + 1}",
                value=value, raw_value=raw_value, unit="percent", raw_unit="%",
                period="FY2025", period_basis="FY", period_type="fiscal_year",
                category_dimensions={"category": label}, validation_status="valid", confidence=.99,
                evidence=[SourceEvidence(page=row + 1, text=f"Reported {raw_value}", row_label=label,
                                         extraction_method="digital_table", confidence=.99)],
            ))
    block = PresentationVisualBlock(role="matrix", matrix_dimension="category",
                                    observation_ids=[item.id for item in observations])
    # A valid long header exposes the capacity failure even for four short rows.
    plan = PresentationSlide(
        id="comparison", slide_type="analysis",
        title="How do the reported category measures compare across the selected reporting period?",
        message="The complete reported values retain their original category and measure context.",
        visual_blocks=[block], source_pages=list(range(1, len(labels) + 1)),
    )
    return observations, block, plan


def _tables(deck):
    return [next(shape for shape in slide.shapes if shape.has_table) for slide in deck.slides]


def _assert_readable(deck):
    """Native cell budgets include all wrapping, margins, and the footer reserve."""
    for shape in _tables(deck):
        assert shape.top.inches + shape.height.inches <= deck.slide_height.inches - 1.02 + 1e-6
        for i, row in enumerate(shape.table.rows):
            font_size, line_height = (12, 15) if i == 0 else (14, 18)
            for j, cell in enumerate(row.cells):
                available = shape.table.columns[j].width.inches - .20
                needed = len(_lines(cell.text, available, font_size)) * line_height / 72 + .12
                assert needed <= row.height.inches + 1e-6
                assert all(paragraph.font.size.pt == font_size for paragraph in cell.text_frame.paragraphs)


def test_four_row_matrix_continues_below_a_tall_valid_header():
    items, block, plan = _matrix(row_count=4)
    before = [item.model_dump(mode="json") for item in items]
    deck = blank_deck()
    first = render_matrix(deck, plan, block, {item.id: item for item in items})

    assert first == deck.slides[0]
    assert len(deck.slides) == 2
    assert [len(shape.table.rows) - 1 for shape in _tables(deck)] == [3, 1]
    assert [item.model_dump(mode="json") for item in items] == before
    _assert_readable(deck)


@pytest.mark.parametrize("column_count", [2, 3, 5])
def test_pagination_keeps_every_cell_label_and_page_specific_source(column_count):
    items, block, plan = _matrix(column_count=column_count)
    deck = blank_deck()
    render_matrix(deck, plan, block, {item.id: item for item in items})
    matrix = comparison_matrix(block, {item.id: item for item in items})
    expected_rows = [[label, *(item.raw_value + "%" for item in records)]
                     for label, records in zip(matrix.row_labels, matrix.cells)]
    actual_rows, retained = [], []
    for page, (slide, shape) in enumerate(zip(deck.slides, _tables(deck)), 1):
        assert [cell.text for cell in shape.table.rows[0].cells] == ["category", *matrix.column_labels]
        actual_rows.extend([cell.text for cell in row.cells] for row in list(shape.table.rows)[1:])
        source = json.loads(slide.notes_slide.notes_text_frame.text)["source_observations"]
        retained.extend(source)
        assert shape.name == "table:comparison_matrix:" + ",".join(item["id"] for item in source)
        visible = "\n".join(s.text for s in slide.shapes if s.has_text_frame)
        assert f"Matrix {page} of {len(deck.slides)}" in visible
        from adaptive_document_agent.services.pptx_export import _source_footer
        assert _source_footer(sorted({e["page"] for item in source for e in item["evidence"]})) in visible
    assert actual_rows == expected_rows
    assert retained == [item.model_dump(mode="json") for item in items]
    _assert_readable(deck)


def test_wrapped_labels_and_raw_values_get_height_instead_of_clipping():
    labels = [f"Category {i}: the detailed regional operating measure with complete qualifying context"
              for i in range(4)]
    items, block, plan = _matrix(labels=labels, raw_values=["12.500 (reported estimate)"] * 4)
    deck = blank_deck()
    render_matrix(deck, plan, block, {item.id: item for item in items})
    tables = _tables(deck)
    assert len(tables) > 1
    assert any(row.height.inches > .78 for shape in tables for row in list(shape.table.rows)[1:])
    assert [row.cells[0].text for shape in tables for row in list(shape.table.rows)[1:]] == labels
    assert all(cell.text == "12.500 (reported estimate)%"
               for shape in tables for row in list(shape.table.rows)[1:] for cell in list(row.cells)[1:])
    _assert_readable(deck)


def test_small_matrix_stays_on_one_slide_without_continuation_label():
    items, block, plan = _matrix(row_count=2)
    deck = blank_deck()
    render_matrix(deck, plan, block, {item.id: item for item in items})
    assert len(deck.slides) == 1
    assert not any("Matrix 1 of" in s.text for s in deck.slides[0].shapes if s.has_text_frame)
    _assert_readable(deck)


def test_a_single_unreadable_row_still_fails_closed():
    items, block, plan = _matrix(labels=["Category " + "qualifying context " * 80, "Short category"])
    with pytest.raises(ValueError, match="row exceeds readable slide capacity"):
        render_matrix(blank_deck(), plan, block, {item.id: item for item in items})


def test_repeated_headers_have_explicit_contrasting_fill_and_text():
    from adaptive_document_agent.services.pptx_export import FOURIER_PURPLE, WHITE

    items, block, plan = _matrix()
    deck = blank_deck()
    render_matrix(deck, plan, block, {item.id: item for item in items})
    for shape in _tables(deck):
        for cell in shape.table.rows[0].cells:
            assert str(cell.fill.fore_color.rgb) == FOURIER_PURPLE
            assert all(str(paragraph.font.color.rgb) == WHITE for paragraph in cell.text_frame.paragraphs)
