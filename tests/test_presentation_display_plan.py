"""Physical pagination preserves facts, qualifiers and the model's topic order."""

from copy import deepcopy

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import PresentationSlide, PresentationVisualBlock, PresentationTheme
from adaptive_document_agent.services.presentation_display_plan import (
    balanced_groups, corroboration_notes, display_slides,
)
from adaptive_document_agent.services.presentation_scope import scope_items, scope_audit_notes
from tests.test_p0_composition import observation, result_for
from adaptive_document_agent.models import ChartPlan


@pytest.mark.parametrize("count, sizes", [(4, [2, 2]), (5, [3, 2]), (7, [3, 2, 2]), (1, [1])])
def test_chart_pagination_keeps_order_and_avoids_single_panel_tail(count, sizes):
    groups = balanced_groups(list(range(count)))
    assert list(map(len, groups)) == sizes
    assert sum(groups, []) == list(range(count))


def duplicate_result():
    values = [observation(str(i), "Operating loss", value, f"FY{2022+i}")
              for i, value in enumerate((-20, -30, -40))]
    for value in values:
        value.validation_status = "valid"
    copies = [value.model_copy(deep=True, update={"id": "copy-" + value.id}) for value in values]
    for value in copies:
        value.evidence[0].page = 8
    chart = ChartPlan(id="loss", title="Operating loss", chart_type="line", question="What changed?",
                      observation_ids=[value.id for value in values], source_pages=[3])
    chart_slide = PresentationSlide(id="primary", slide_type="analysis", title="Loss trend",
        theme_id="performance", message="What changed?", chart_ids=[chart.id], source_pages=[3])
    result = result_for(values + copies, [chart], chart_slide)
    result.presentation_plan.slides.insert(4, PresentationSlide(id="copy", slide_type="analysis",
        title="Loss trend", theme_id="performance", message="What changed?", source_pages=[8],
        observation_ids=[value.id for value in copies],
        visual_blocks=[PresentationVisualBlock(role="table", observation_ids=[value.id for value in copies])]))
    return result


def test_complete_corroborating_table_shares_chart_page_but_retains_every_record():
    result = duplicate_result()
    before = deepcopy(result.model_dump())
    index = DocumentIndex(result.observations)
    pages = display_slides(result.presentation_plan, {chart.id: chart for chart in result.charts}, index)
    assert [page.id for page in pages if page.slide_type == "analysis"] == ["primary"]
    owner = next(page for page in pages if page.id == "primary")
    assert owner.source_pages == [3, 8]
    notes = corroboration_notes(owner, index)
    assert all("copy-" + str(number) in notes for number in range(3))
    assert result.model_dump() == before


@pytest.mark.parametrize("change", ["value", "period", "ifrs", "raw_unit", "category", "partial", "claim"])
def test_different_or_partial_evidence_cannot_be_deduplicated(change):
    result = duplicate_result()
    item = result.observations[-1]
    table = result.presentation_plan.slides[4]
    if change == "value": item.value = -41
    if change == "period": item.period = "FY2025"
    if change == "ifrs": item.ifrs_status = "non-IFRS"
    if change == "raw_unit": item.raw_unit = "USD thousand"
    if change == "category": item.category_dimensions = {"segment": "Services"}
    if change == "partial":
        table.observation_ids = table.observation_ids[:-1]
        table.visual_blocks[0].observation_ids = table.visual_blocks[0].observation_ids[:-1]
    if change == "claim": table.bullets = ["A separately supported finding."]
    pages = display_slides(result.presentation_plan, {chart.id: chart for chart in result.charts}, DocumentIndex(result.observations))
    assert len([page for page in pages if page.slide_type == "analysis"]) == 2


def test_editorial_priorities_stay_in_audit_and_material_limit_stays_visible():
    result = duplicate_result()
    result.presentation_plan.coverage_notes = [
        "Adjusted result: Adjusted result is redundant with the selected reported result.",
        "Inventory: Detail is omitted to keep the selected topic concise.",
        "Supplier-level breakdown is not shown.",
    ]
    result.presentation_plan.themes = [PresentationTheme(id="performance", title="Performance",
        question="What changed?", rationale="Compare results.", caveats=["Annual periods only."])]
    visible = "\n".join(item.text for item in scope_items(result))
    assert "redundant" not in visible and "omitted to keep" not in visible
    assert "Supplier-level" in visible
    assert "Annual periods only" not in visible  # now beside the relevant visual
    audit = scope_audit_notes(result)
    assert "redundant" in audit and "Annual periods only" in audit


def test_special_visual_without_local_context_renderer_keeps_scope_caveats():
    result = duplicate_result()
    result.presentation_plan.slides[3].visual_blocks = [PresentationVisualBlock(role="waterfall")]
    result.presentation_plan.themes = [PresentationTheme(id="performance", title="Performance",
        question="What changed?", rationale="Compare results.", caveats=["Reported bridge excludes estimates."])]
    assert "Reported bridge excludes estimates." in [item.text for item in scope_items(result)]


def test_appendix_keeps_fitting_category_topic_together():
    from adaptive_document_agent.services.appendix_layout import paginate_themes
    themes = [("Amounts", {str(i): {} for i in range(4)}),
              ("Category composition", {str(i): {} for i in range(4)}),
              ("Ratios", {"a": {}})]
    pages = paginate_themes(themes, capacity=8)
    assert len(pages) == 2
    assert sum(any(theme == "Category composition" for theme, _ in page) for page in pages) == 1


def test_complete_topic_takes_precedence_over_saving_a_page_by_splitting_it():
    from adaptive_document_agent.services.appendix_layout import paginate_themes
    themes = [(f"Topic {number}", {str(i): {} for i in range(4)}) for number in range(3)]
    pages = paginate_themes(themes, capacity=8)
    assert len(pages) == 3
    assert all(sum(theme == name for page in pages for theme, _ in page) == 1
               for name, _ in themes)


def test_mixed_chart_page_shows_only_bound_ratio_definition_next_to_evidence():
    from adaptive_document_agent.models import DocumentPage
    from adaptive_document_agent.services.slide_compositor import render_composed_slide, validate_composed_geometry
    from tests.test_presentation_brief import blank_deck, visible
    observations, charts = [], []
    for metric, unit, amounts in [("Occupied slots", "count", (20, 30)),
                                 ("Capacity ratio", "percent", (20, 30))]:
        items = [observation(metric + str(i), metric, amount, f"FY{2023+i}", unit=unit)
                 for i, amount in enumerate(amounts)]
        for item in items:
            item.validation_status = "valid"
            item.table_id = "capacity-table"
            item.evidence[0].table_id = "capacity-table"
        observations.extend(items)
        charts.append(ChartPlan(id=metric, title=metric, chart_type="line", question="What changed?",
                               observation_ids=[item.id for item in items]))
    result = result_for(observations, charts)
    result.document.pages = [DocumentPage(page_number=3, text=(
        "Capacity ratio (1) 20 30\n(1) Calculated by dividing occupied slots by available slots."))]
    deck = blank_deck()
    rendered = render_composed_slide(deck, result.presentation_plan.slides[3], charts, result,
                                    DocumentIndex(result.observations))
    assert len(rendered) == 1
    assert "Capacity ratio: occupied slots / available slots" in visible(rendered[0])
    assert "Occupied slots: occupied slots / available slots" not in visible(rendered[0])
    validate_composed_geometry(deck)
