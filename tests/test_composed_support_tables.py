"""Small sourced period tables fit their support band before creating a new page."""

from copy import deepcopy

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import PresentationVisualBlock
from adaptive_document_agent.services.slide_compositor import render_composed_slide, validate_composed_geometry
from tests.test_p0_composition import observation, paired_result
from tests.test_presentation_brief import blank_deck


def _supported_result(label):
    result = paired_result(layout="two_up")
    support = [observation(f"support-{year}", label, value, f"FY{year}", unit="percent")
               for year, value in [(2021, 68.8), (2022, 41.9), (2023, 34.7)]]
    result.observations.extend(support)
    plan = result.presentation_plan.slides[3]
    plan.visual_blocks[-1] = PresentationVisualBlock(role="table", observation_ids=[item.id for item in support])
    plan.bullets = ["The disclosed interim observations remain outside this annual comparison."]
    return result, support


def _render(result):
    deck = blank_deck()
    plan = result.presentation_plan.slides[3]
    slides = render_composed_slide(deck, plan, result.charts, result, DocumentIndex(result.observations))
    validate_composed_geometry(deck)
    return deck, slides


@pytest.mark.parametrize("label", ["Remote devices: %of Total", "Plant North production share", "研究样本占总数比例"])
def test_complete_three_period_support_fits_beside_commentary_without_sparse_continuation(label):
    result, support = _supported_result(label)
    before = result.model_dump_json()
    deck, slides = _render(result)

    assert len(slides) == 1
    assert sum(shape.has_chart for shape in slides[0].shapes) == 2
    shape = next(shape for shape in slides[0].shapes if shape.has_table)
    table = shape.table
    assert len(table.rows) == 2 and len(table.columns) == 4
    assert [table.cell(0, column).text for column in range(1, 4)] == ["FY2021", "FY2022", "FY2023"]
    assert [table.cell(1, column).text for column in range(1, 4)] == ["68.8%", "41.9%", "34.7%"]
    assert "".join(table.cell(1, 0).text.split()) == "".join(label.split())
    assert shape.height.inches <= 1.22
    assert all(paragraph.font.size.pt == 14 for row in table.rows for cell in row.cells
               for paragraph in cell.text_frame.paragraphs)
    assert all(item.id in slides[0].notes_slide.notes_text_frame.text for item in support)
    assert result.model_dump_json() == before


def test_table_layout_keeps_conflicting_period_values_visible():
    result, support = _supported_result("Measured participation share")
    conflict = support[0].model_copy(deep=True)
    conflict.id = "conflicting-source"
    conflict.value, conflict.raw_value = 67.8, "67.8"
    conflict.evidence[0].page = 4
    result.observations.append(conflict)
    result.presentation_plan.slides[3].visual_blocks[-1].observation_ids.append(conflict.id)
    _, slides = _render(result)
    values = [cell.text for slide in slides for shape in slide.shapes if shape.has_table
              for row in shape.table.rows for cell in row.cells]
    assert all(value in values for value in ["68.8%", "67.8%", "41.9%", "34.7%"])
    assert all(item.id in slides[0].notes_slide.notes_text_frame.text for item in [*support, conflict])


def test_support_table_does_not_drop_the_category_from_a_parent_label():
    result, support = _supported_result("Current liabilities")
    for item in support:
        item.category_dimensions = {"category": "Trade and bills payables"}
        item.dimensions = dict(item.category_dimensions)
    before = result.model_dump_json()
    _, slides = _render(result)
    labels = [cell.text.replace("\n", " ") for slide in slides for shape in slide.shapes if shape.has_table
              for row in shape.table.rows for cell in row.cells]
    assert any("Trade and bills payables" in label for label in labels)
    assert not any(label == "Current liabilities" for label in labels)
    assert result.model_dump_json() == before


def test_table_layout_does_not_pivot_incompatible_period_bases_into_one_series():
    result, support = _supported_result("Measured participation share")
    support[-1].period = "6M2023"
    support[-1].period_basis = "6M"
    before = deepcopy(support)
    _, slides = _render(result)
    tables = [shape.table for slide in slides for shape in slide.shapes if shape.has_table]
    # These remain explicit records, not a matrix that appears like comparable
    # consecutive annual periods.
    assert all([table.cell(0, c).text for c in range(len(table.columns))] == ["Metric", "Period", "Value"]
               for table in tables)
    cells = [cell.text.replace("\n", "") for table in tables for row in table.rows for cell in row.cells]
    assert "6M2023" in cells
    assert support == before


def test_long_qualified_label_still_continues_when_a_readable_table_cannot_fit():
    label = "Measured participation share for the specifically disclosed eligible population"
    result, support = _supported_result(label)
    _, slides = _render(result)
    assert len(slides) > 1
    cells = [cell.text for slide in slides for shape in slide.shapes if shape.has_table
             for row in shape.table.rows for cell in row.cells]
    assert all(value in cells for value in ["68.8%", "41.9%", "34.7%"])
    assert any("".join(cell.split()) == "".join(label.split()) for cell in cells)
    assert all(item.id in slides[0].notes_slide.notes_text_frame.text for item in support)
