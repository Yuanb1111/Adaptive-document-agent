"""Native matrices compare only complete, explicitly selected categories."""

import pytest

from adaptive_document_agent.models import Observation, PresentationSlide, PresentationVisualBlock, SourceEvidence
from adaptive_document_agent.services.presentation_matrix import (
    comparison_matrix, render_matrix, topic_matrix_dimension,
)
from tests.test_presentation_brief import blank_deck


def _records():
    items = []
    for category, values in (("Service A", (20, 30)), ("Service B", (12, 25))):
        for name, value in zip(("Users", "Retention rate"), values):
            items.append(Observation(
                id=f"{category}-{name}", metric_original=name, value=value, raw_value=str(value),
                unit="percent" if name == "Retention rate" else "count",
                raw_unit="%" if name == "Retention rate" else "users",
                period="FY2025", period_basis="FY", period_type="fiscal_year",
                category_dimensions={"service": category}, validation_status="valid", confidence=.99,
                evidence=[SourceEvidence(page=3, text=str(value), row_label=category,
                                         extraction_method="digital_table", confidence=.99)],
            ))
    block = PresentationVisualBlock(role="matrix", matrix_dimension="service",
                                    observation_ids=[item.id for item in items])
    return items, block


def test_complete_matrix_renders_all_source_cells_as_editable_table():
    items, block = _records()
    matrix = comparison_matrix(block, {item.id: item for item in items})
    assert matrix.row_labels == ("Service A", "Service B")
    assert len(matrix.column_labels) == 2
    deck = blank_deck()
    plan = PresentationSlide(id="comparison", slide_type="analysis", title="Service comparison",
                             section_title="Services", message="Compare reported service measures.",
                             visual_blocks=[block], source_pages=[3])
    slide = render_matrix(deck, plan, block, {item.id: item for item in items})
    table = next(shape.table for shape in slide.shapes if shape.has_table)
    assert len(table.rows) == 3 and len(table.columns) == 3
    assert all(item.id in slide.notes_slide.notes_text_frame.text for item in items)


def test_missing_or_conflicting_matrix_cell_is_never_filled():
    items, block = _records()
    block.observation_ids.pop()
    with pytest.raises(ValueError, match="Matrix needs|missing"):
        comparison_matrix(block, {item.id: item for item in items})
    items, block = _records()
    extra = items[0].model_copy(deep=True, update={"id": "duplicate", "value": 999})
    block.observation_ids.append(extra.id)
    with pytest.raises(ValueError, match="duplicate"):
        comparison_matrix(block, {item.id: item for item in [*items, extra]})


def test_parallel_source_metrics_form_a_complete_period_matrix() -> None:
    items = [Observation(
        id=f"{name}-{year}", metric_original=f"{name}: share of total",
        value=value, raw_value=str(value), unit="percent", raw_unit="%",
        period=f"FY{year}", period_basis="FY", period_type="fiscal_year",
        validation_status="valid", confidence=.99,
        evidence=[SourceEvidence(page=4, text=str(value), extraction_method="digital_table", confidence=.99)],
    ) for name, values in (("North", (15, 18, 20)), ("South", (25, 23, 21)),
                         ("East", (35, 34, 33)), ("West", (20, 22, 24)))
    for year, value in zip((2022, 2023, 2024), values)]
    assert topic_matrix_dimension(items) == "source_metric"
    block = PresentationVisualBlock(role="matrix", matrix_dimension="source_metric",
                                    observation_ids=[item.id for item in items])
    matrix = comparison_matrix(block, {item.id: item for item in items})
    assert len(matrix.row_labels) == 4 and len(matrix.column_labels) == 3
    assert matrix.column_labels[0].startswith("FY2022")
    assert topic_matrix_dimension(items[:-1]) is None
