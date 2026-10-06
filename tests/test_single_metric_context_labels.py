"""Standalone metric pages retain units and row-bound definition context."""

import json

import pytest

from adaptive_document_agent.models import ChartPlan, DocumentPage
from adaptive_document_agent.services.pptx_export import _build_planned_presentation, _classify_financial_theme
from adaptive_document_agent.services.single_metric_analysis import single_metric_analysis
from adaptive_document_agent.services.single_metric_renderer import add_single_metric_slide
from tests.test_presentation_brief import blank_deck, visible
from tests.test_single_metric_enrichment import result_for, series


def test_percentage_levels_keep_percent_units_and_changes_remain_percentage_points():
    observations = series((20, 30, 25), metric="Capacity ratio %", unit="percent")
    chart = ChartPlan(id="capacity", title="Capacity ratio %", chart_type="line", question="",
                      observation_ids=[o.id for o in observations])
    before = [o.model_dump() for o in observations]
    deck = blank_deck()
    slide = add_single_metric_slide(deck, chart, single_metric_analysis(observations),
                                    title="Capacity ratio %", narrative="")
    copy = visible(slide)
    assert "20.0%" in copy and "25.0%" in copy and "30.0%" in copy
    assert "Change (pp)" in copy and "percentage points" in copy
    assert "% (%)" not in copy
    assert [o.model_dump() for o in observations] == before
    assert list(next(s.chart for s in slide.shapes if s.has_chart).series[0].values) == [20, 30, 25]


@pytest.mark.parametrize("bound", [True, False])
def test_planned_hero_uses_only_its_own_source_ratio_definition(bound):
    observations = series((20, 30, 25), metric="Capacity ratio", unit="percent")
    for item in observations:
        item.table_id = "capacity-table"
        item.evidence[0].table_id = "capacity-table"
    result = result_for(observations)
    result.presentation_plan.slides[3].layout = "single_metric_hero"
    anchor = "Capacity ratio" if bound else "Unrelated ratio"
    result.document.pages = [DocumentPage(page_number=3, text=(
        f"{anchor} (1) 20 30 25\n"
        "(1) Calculated by dividing occupied slots by available slots."
    ))]
    before = [o.model_dump() for o in observations]
    deck = blank_deck()
    _build_planned_presentation(deck, result)
    slide = next(s for s in deck.slides if s.name == "single_metric_hero")
    definition_shapes = [s for s in slide.shapes if s.name == "single_metric:definition"]
    assert bool(definition_shapes) == bound
    if bound:
        caption = definition_shapes[0]
        assert "occupied slots / available slots" in caption.text
        chart = next(s for s in slide.shapes if s.has_chart)
        assert caption.top + caption.height <= chart.top
        notes = json.loads(slide.notes_slide.notes_text_frame.text)
        assert notes["source_ratio_definition"]["page"] == 3
        assert notes["source_ratio_definition"]["observation_ids"] == [o.id for o in observations]
    assert [o.model_dump() for o in observations] == before


@pytest.mark.parametrize("name", ["Total non-current assets", "Other non current liabilities", "NONCURRENT ASSETS"])
def test_noncurrent_balances_are_not_classified_as_liquidity(name):
    assert _classify_financial_theme(name) == "Financial Overview"


def test_current_balances_still_use_liquidity_classification():
    assert _classify_financial_theme("Total current assets") == "Liquidity"
    assert _classify_financial_theme("Current liabilities") == "Liquidity"


def test_noncurrent_qualifier_preserves_stronger_source_context():
    assert _classify_financial_theme("Cash flow from disposal of non-current assets") == "Cash Flow"
    assert _classify_financial_theme("Non-current liabilities", "Capital Structure & Indebtedness") == "Capital Structure & Indebtedness"


def test_source_table_caption_is_visible_without_rewriting_the_original_measure():
    observations = series((60, 55, 50), metric="Sample A: %of Total", unit="percent")
    before = [o.model_dump() for o in observations]
    chart = ChartPlan(id="share", title="Sample A: %of Total", chart_type="line", question="",
                      observation_ids=[o.id for o in observations])
    context = "This table reports the distribution of measured output by production location."
    slide = add_single_metric_slide(blank_deck(), chart, single_metric_analysis(observations),
        title=chart.title, narrative="", source_context=context)
    assert "Sample A: % of Total" in visible(slide)
    assert context in visible(slide)
    assert json.loads(slide.notes_slide.notes_text_frame.text)["planned_title"] == chart.title
    assert [o.model_dump() for o in observations] == before
