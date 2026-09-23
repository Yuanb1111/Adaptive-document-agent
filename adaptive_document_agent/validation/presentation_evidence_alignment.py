"""Align redundant slide references with the coherent series used by its charts."""

from __future__ import annotations

from collections import defaultdict
from math import isclose

from adaptive_document_agent.document_model.series import source_context_key
from adaptive_document_agent.models import ChartPlan, Observation, PresentationPlan


def _same_reported_fact(left: Observation, right: Observation) -> bool:
    """Require an exact-period, exact-value duplicate, not merely a shared label."""
    if left.value is None or right.value is None:
        return False
    excluded_dimensions = {"section", "table_context"}
    left_dimensions = {k: v for k, v in left.dimensions.items() if k not in excluded_dimensions}
    right_dimensions = {k: v for k, v in right.dimensions.items() if k not in excluded_dimensions}
    return (
        left.metric_original.strip().casefold() == right.metric_original.strip().casefold()
        and (left.metric_canonical or "").strip().casefold()
        == (right.metric_canonical or "").strip().casefold()
        and left.period == right.period
        and left.entity == right.entity
        and left_dimensions == right_dimensions
        and left.category_dimensions == right.category_dimensions
        and left.unit == right.unit
        and left.raw_unit == right.raw_unit
        and left.unit_scale == right.unit_scale
        and left.unit_family == right.unit_family
        and left.currency == right.currency
        and left.period_type == right.period_type
        and left.period_basis == right.period_basis
        and left.ifrs_status == right.ifrs_status
        and left.fact_type == right.fact_type
        and isclose(float(left.value), float(right.value), rel_tol=1e-12, abs_tol=1e-9)
    )


def align_redundant_slide_evidence(
    plan: PresentationPlan,
    observations: list[Observation],
    charts: list[ChartPlan] | None,
) -> list[str]:
    """Replace only proven duplicate references; leave conflicting contexts blocked.

    A chart's own observation IDs establish its plotted source series. Model-written
    slide plans can also cite a second table containing the same reported facts.
    Reconcile those references only when at least two distinct periods match one
    coherent chart series and every referenced fact in that source group matches.
    Raw observations and their original provenance remain unchanged.
    """
    if not charts:
        return []
    obs_by_id = {item.id: item for item in observations}
    chart_by_id = {item.id: item for item in charts}
    repairs: list[str] = []

    for slide in plan.slides:
        chart_ids = set(slide.chart_ids) | {
            chart_id for block in slide.visual_blocks for chart_id in block.chart_ids
        }
        chart_series: dict[tuple[str, tuple[str, str], str], list[Observation]] = defaultdict(list)
        for chart_id in chart_ids:
            chart = chart_by_id.get(chart_id)
            if chart is None:
                continue
            for obs_id in chart.observation_ids:
                obs = obs_by_id.get(obs_id)
                if obs is not None and obs.period and obs.value is not None:
                    key = (obs.metric_original.strip().casefold(), source_context_key(obs), chart_id)
                    chart_series[key].append(obs)

        direct_ids = set(slide.observation_ids) | {
            obs_id for block in slide.visual_blocks for obs_id in block.observation_ids
        }
        direct_series: dict[tuple[str, tuple[str, str]], list[Observation]] = defaultdict(list)
        for obs_id in direct_ids:
            obs = obs_by_id.get(obs_id)
            if obs is not None and obs.period and obs.value is not None:
                key = (obs.metric_original.strip().casefold(), source_context_key(obs))
                direct_series[key].append(obs)

        replacements: dict[str, str] = {}
        for (metric, context), direct in direct_series.items():
            if len({item.period for item in direct}) < 2:
                continue
            candidates: list[dict[str, str]] = []
            for (chart_metric, chart_context, _), series in chart_series.items():
                if chart_metric != metric or chart_context == context or len({item.period for item in series}) < 2:
                    continue
                matches: dict[str, str] = {}
                for item in direct:
                    peers = [candidate for candidate in series if _same_reported_fact(item, candidate)]
                    if len(peers) != 1:
                        break
                    matches[item.id] = peers[0].id
                if len(matches) == len(direct):
                    candidates.append(matches)
            if len(candidates) == 1:
                replacements.update(candidates[0])

        if not replacements:
            continue
        slide.observation_ids = list(dict.fromkeys(replacements.get(oid, oid) for oid in slide.observation_ids))
        for block in slide.visual_blocks:
            block.observation_ids = list(dict.fromkeys(replacements.get(oid, oid) for oid in block.observation_ids))

        # Discard only citations that belonged exclusively to removed duplicate
        # observations. Insight citations are not available here, so retain all
        # existing pages on slides that cite insights.
        if not slide.insight_ids:
            replaced_pages = {
                source.page for old_id in replacements for source in obs_by_id[old_id].evidence
            }
            retained_ids = set(slide.observation_ids) | {
                oid for block in slide.visual_blocks for oid in block.observation_ids
            }
            retained_pages = {
                source.page for oid in retained_ids if oid in obs_by_id
                for source in obs_by_id[oid].evidence
            }
            for chart_id in chart_ids:
                chart = chart_by_id.get(chart_id)
                if chart is not None:
                    retained_pages.update(chart.source_pages)
                    retained_pages.update(
                        source.page for oid in [*chart.observation_ids, *chart.total_observation_ids]
                        if oid in obs_by_id for source in obs_by_id[oid].evidence
                    )
            slide.source_pages = [
                page for page in slide.source_pages
                if page not in replaced_pages or page in retained_pages
            ]
        repairs.append(
            f"Slide {slide.id}: aligned {len(replacements)} duplicate observation references "
            "with their chart source series"
        )
    return repairs
