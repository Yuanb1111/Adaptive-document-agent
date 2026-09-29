"""A waterfall requires a complete source reconciliation."""

import pytest

from adaptive_document_agent.models import Observation, PresentationSlide, PresentationVisualBlock, SourceEvidence
from adaptive_document_agent.services.presentation_waterfall import waterfall_data, render_waterfall
from tests.test_presentation_brief import blank_deck


def _bridge(values=(100, 30, -10, 120)):
    labels = ("Opening measure", "Addition", "Deduction", "Closing measure")
    items = [Observation(
        id=f"o-{i}", metric_original=label, value=value, raw_value=str(value),
        unit="count", raw_unit="units", period="FY2025", period_basis="FY",
        period_type="fiscal_year", table_id="reported-bridge", validation_status="valid",
        confidence=.99,
        evidence=[SourceEvidence(page=4, text=str(value), row_label=label,
                                 extraction_method="digital_table", confidence=.99)],
    ) for i, (label, value) in enumerate(zip(labels, values))]
    block = PresentationVisualBlock(role="waterfall", observation_ids=[item.id for item in items])
    return items, block


def test_reconciled_bridge_renders_editable_chart_and_exact_rows():
    items, block = _bridge()
    bridge = waterfall_data(block, {item.id: item for item in items})
    assert bridge.levels == (100, 130, 120, 120)
    slide_plan = PresentationSlide(id="bridge", slide_type="analysis", title="Reported components reconcile",
                                   section_title="Components", message="The selected source table reconciles.",
                                   visual_blocks=[block], source_pages=[4])
    deck = blank_deck()
    slide = render_waterfall(deck, slide_plan, block, {item.id: item for item in items})
    assert any(shape.has_chart for shape in slide.shapes)
    assert any(shape.has_table for shape in slide.shapes)
    assert all(item.id in slide.notes_slide.notes_text_frame.text for item in items)


def test_incomplete_or_mixed_scope_bridge_is_rejected():
    items, block = _bridge(values=(100, 30, -10, 119))
    with pytest.raises(ValueError, match="reconcile"):
        waterfall_data(block, {item.id: item for item in items})
    items[-1].value = 120
    items[-1].table_id = "another-source"
    with pytest.raises(ValueError, match="source table"):
        waterfall_data(block, {item.id: item for item in items})
