"""Preserve selected composition evidence independently of takeaway wording."""

from __future__ import annotations

import re

from adaptive_document_agent.models import PresentationSlide, PresentationVisualBlock
from adaptive_document_agent.utils.ids import stable_id
from .composition_data import composition_data, uses_composition_data
from .presentation_evidence import ambiguous_source_table_ids, observation_uses_ambiguous_table


def _selected_matrices(result, plan):
    """Validate the exact theme-selected charts, never substitute another mix."""
    charts = {chart.id: chart for chart in result.charts}
    observations = {item.id: item for item in result.observations}
    ambiguous = ambiguous_source_table_ids(result)
    for theme in plan.themes:
        for chart_id in theme.chart_ids:
            chart = charts.get(chart_id)
            if chart is None or not uses_composition_data(chart):
                continue
            ids = [*chart.observation_ids, *chart.total_observation_ids]
            matrix = None
            if (set(ids) <= set(theme.observation_ids) and all(oid in observations for oid in ids)
                    and not any(observation_uses_ambiguous_table(observations[oid], ambiguous) for oid in ids)):
                try:
                    matrix = composition_data(chart, [observations[oid] for oid in chart.observation_ids],
                                              [observations[oid] for oid in chart.total_observation_ids])
                except ValueError:
                    pass  # Invalid composition remains blocked by its original evidence guard.
            yield theme, chart, matrix


def restore_selected_compositions(result, plan):
    """Recover a chart removed by subset-only enrichment, preserving source facts.

    A compact table can share a page with the complete selected composition.
    Advanced standalone visuals keep their page; the missing mix gets its own
    source-bound continuation. No source observations or chart data are edited.
    """
    from .presentation_claim_evidence import visible_observation_ids

    charts = {chart.id: chart for chart in result.charts}
    observations = {item.id: item for item in result.observations}
    notes = []
    for theme, chart, matrix in _selected_matrices(result, plan):
        if matrix is None:
            continue
        slides = [slide for slide in plan.slides if slide.slide_type == "analysis" and slide.theme_id == theme.id]
        visible = {oid for slide in slides for oid in visible_observation_ids(slide, charts)}
        if not slides or set(chart.observation_ids) <= visible:
            continue
        slide = slides[0]
        direct = list(dict.fromkeys([*slide.observation_ids,
                                    *(oid for block in slide.visual_blocks for oid in block.observation_ids)]))
        blocks_are_data = all(block.role in {"table", "kpi"} and not block.insight_ids
                              and not block.chart_ids for block in slide.visual_blocks)
        existing = set(slide.chart_ids)
        # Matrices carry row/column category identity that a generic value
        # table cannot preserve. Keep them and other standalone views intact;
        # the selected composition receives its own source-bound continuation.
        # Never imply that another page's evidence is visible here.
        if (len(slides) == 1 and blocks_are_data and len(direct) <= 12
                and len(existing | {chart.id}) <= 3 and set(direct) <= observations.keys()):
            slide.chart_ids = list(dict.fromkeys([chart.id, *slide.chart_ids]))
            slide.visual_blocks = [PresentationVisualBlock(role="table", observation_ids=direct)] if direct else []
            slide.observation_ids = direct
            slide.layout = ("chart_with_data" if direct else
                            {1: "single", 2: "two_up", 3: "three_up"}[len(slide.chart_ids)])
            all_ids = set(direct) | {oid for cid in slide.chart_ids for oid in
                                     [*charts[cid].observation_ids, *charts[cid].total_observation_ids]}
            slide.source_pages = sorted({e.page for oid in all_ids if oid in observations for e in observations[oid].evidence})
        else:
            recovered = PresentationSlide(
                id=stable_id("selected_composition", theme.id, chart.id), slide_type="analysis",
                title=chart.question, message=chart.question, section_id=theme.id,
                section_title=theme.title, slide_role="deep_dive", layout="single",
                theme_id=theme.id, chart_ids=[chart.id], source_pages=matrix.source_pages,
                analytical_question=chart.question, selection_reason=theme.rationale,
            )
            plan.slides.insert(plan.slides.index(slides[-1]) + 1, recovered)
        notes.append(f"Theme {theme.id}: restored its complete selected composition alongside the retained analysis evidence")
    return notes


_COVERAGE = re.compile(
    r"^(?:the\s+)?composition\s+(?:covers?|includes?|contains?)\s+"
    r"(?:all|the\s+(?:full|complete))\s+(?:[\w-]+\s+){0,3}(?:categories|matrix|mix)[.!]?$", re.I,
)
_REDUNDANT = re.compile(r"\bredundant\b.*\b(?:composition|mix)\b|\bselected\b.*\bcomposition\b", re.I)


def reconcile_composition_coverage(result, plan):
    """Derive audience composition coverage from validated visible selections."""
    from .presentation_claim_evidence import visible_observation_ids

    charts = {chart.id: chart for chart in result.charts}
    by_theme = {}
    for theme, chart, matrix in _selected_matrices(result, plan):
        visible = {oid for slide in plan.slides if slide.slide_type == "analysis" and slide.theme_id == theme.id
                   for oid in visible_observation_ids(slide, charts)}
        displayed = matrix is not None and set(chart.observation_ids) <= visible
        by_theme.setdefault(theme.id, (theme, []))[1].append((chart, matrix, displayed))
    unavailable = []
    for theme, selected in by_theme.values():
        missing = [chart for chart, _, displayed in selected if not displayed]
        if missing:
            text = "Selected composition is not displayed: its complete validated matrix is unavailable in the rendered analysis."
            unavailable.extend(missing)
        else:
            text = "Displayed composition covers the validated selected-category matrix for its cited periods."
        updated = []
        for note in theme.caveats:
            parts = re.split(r";\s*|(?<=[.!?])\s+", note)
            retained = [part for part in parts if not _COVERAGE.fullmatch(part)
                        and not part.startswith(("Selected composition is not displayed:",
                                                 "Displayed composition covers the complete validated",
                                                 "Displayed composition covers the validated selected-category"))]
            if retained:
                updated.append("; ".join(retained))
        # Preserve unrelated qualifications even when the schema's caveat
        # capacity is full, rather than truncating a user-visible limitation.
        if len(updated) >= 5:
            updated[-1] += " " + text
        else:
            updated.append(text)
        theme.caveats = list(dict.fromkeys(updated))
    if unavailable:
        plan.coverage_notes = [
            "Composition coverage is limited to the validated views actually displayed; "
            "an omitted individual category must not be assumed covered by a selected composition."
            if _REDUNDANT.search(note) else note for note in plan.coverage_notes
        ]
