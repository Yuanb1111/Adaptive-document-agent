"""Whole-composition captions never masquerade as one reported component."""

import json

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import PresentationSlide, PresentationVisualBlock
from adaptive_document_agent.services.presentation_labels import (
    composition_heading, composition_message, qualified_metric_name, readable_chart_heading,
)
from adaptive_document_agent.services.slide_compositor import render_composed_slide
from tests.test_p0_composition import matrix, result_for
from tests.test_presentation_scope_labels import _deck


@pytest.mark.parametrize("metric,categories", [
    ("Survey responses", ("Agree", "Disagree")),
    ("Production share", ("Plant North", "Plant South")),
    ("Programme share", ("Research and development", "Training, support")),
])
def test_component_headings_and_exact_inventories_scope_to_the_authored_composition(metric, categories):
    observations, chart = matrix(metric=metric, categories=categories)
    chart.question = "How does the reported category mix compare?"
    before = [item.model_dump() for item in observations]
    aliases = [qualified_metric_name(item) for item in observations[:2]]
    inventory = " and ".join(aliases)
    slide = PresentationSlide(id="mix", slide_type="analysis", title=inventory,
        message=inventory, section_title=categories[0], layout="single",
        chart_ids=[chart.id], visual_blocks=[PresentationVisualBlock(
            role="hero", title=aliases[0], chart_ids=[chart.id])], source_pages=[3])
    planned = slide.model_dump()
    deck = _deck()
    render_composed_slide(deck, slide, [chart], result_for(observations, [chart], slide), DocumentIndex(observations))

    assert len(deck.slides) == 1
    visible = "\n".join(shape.text for shape in deck.slides[0].shapes if shape.has_text_frame)
    assert visible.count(metric) == 2  # whole-slide title and chart caption
    assert inventory not in visible
    assert chart.question in visible
    native = next(shape.chart for shape in deck.slides[0].shapes if shape.has_chart)
    assert {series.name for series in native.series} == set(categories)
    assert sorted(tuple(series.values) for series in native.series) == [(0.4, 0.4), (0.6, 0.6)]
    notes = json.loads(deck.slides[0].notes_slide.notes_text_frame.text)
    assert notes["planned_title"] == inventory and notes["analytical_question"] == inventory
    assert {item["id"] for item in notes["observations"]} == {item.id for item in observations}
    assert [item.model_dump() for item in observations] == before
    assert slide.model_dump() == planned


def test_source_row_scope_uses_explicit_column_without_inventing_a_denominator():
    from tests.test_source_row_composition import source_matrix
    from adaptive_document_agent.services.composition_candidates import presentation_compositions

    observations = source_matrix()
    for index, item in enumerate(observations):
        item.metric_original = item.metric_original.replace("% of", "%of")
        item.evidence[0].column_label = "%of Total"
        item.dimensions["table_context"] = "Revenue" if index % 2 else "Unrelated operational context"
    before = [item.model_dump() for item in observations]
    chart = next(item for item in presentation_compositions(DocumentIndex(observations)) if item.chart_type == "stacked_percent")
    assert readable_chart_heading(chart.title, composition=True) == "Category share of total"
    for heading in ("Hardware", "Hardware: %of Total", "Hardware: % of Total"):
        assert composition_heading(heading, chart, observations) == "Category share of total"
    inventory = ", ".join(dict.fromkeys(item.metric_original for item in observations))
    assert composition_heading(inventory, chart, observations) == "Category share of total"
    assert [item.model_dump() for item in observations] == before


@pytest.mark.parametrize("title", [
    "Plant North gained share as Plant South declined",
    "Survey responses remain mixed despite the reported improvement",
    "Reported composition, subject to rounding",
])
def test_authored_takeaways_and_qualifiers_are_not_rewritten(title):
    observations, chart = matrix(metric="Production share", categories=("Plant North", "Plant South"))
    assert composition_heading(title, chart, observations) == title
    assert composition_message(title, chart, observations) == title


def test_common_measure_and_partial_inventory_do_not_become_component_labels():
    observations, chart = matrix(metric="Responses", categories=("Agree", "Disagree"))
    assert composition_heading("Responses", chart, observations) == "Responses"
    assert composition_message("Agree", chart, observations) == "Agree"
    observations[0].value = -40
    with pytest.raises(ValueError, match="negative"):
        composition_heading("Agree", chart, observations)
