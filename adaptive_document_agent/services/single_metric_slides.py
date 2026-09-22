"""Enrich valid single-metric analysis plans with a native chart and calculated KPIs."""

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.document_model.topic_matcher import is_positive_topic_mismatch
from adaptive_document_agent.models import ChartPlan, PipelineResult
from adaptive_document_agent.utils.ids import stable_id

from .single_metric_analysis import single_metric_analysis


def enrich_single_metric_slides(result: PipelineResult) -> list[str]:
    if not result.presentation_plan:
        return []
    obs_by_id = {o.id: o for o in result.observations}
    charts = {c.id: c for c in result.charts}
    enriched = []
    for slide in result.presentation_plan.slides:
        if slide.slide_type != "analysis":
            continue
        # Explicit composition and theme decisions belong to the planner.
        legacy_overview = result.presentation_plan.planning_origin == "legacy" and slide.layout == "data_overview"
        if slide.theme_id or (slide.layout not in {"auto", "single", "single_metric_hero"} and not legacy_overview):
            continue
        if slide.bullets or slide.insight_ids or any(b.role in {"kpi", "table", "commentary"} or b.insight_ids for b in slide.visual_blocks):
            continue
        chart_ids = list(dict.fromkeys(slide.chart_ids + [cid for b in slide.visual_blocks for cid in b.chart_ids]))
        if len(chart_ids) > 1 or any(cid not in charts for cid in chart_ids):
            continue
        obs_ids = list(dict.fromkeys(
            slide.observation_ids + [oid for b in slide.visual_blocks for oid in b.observation_ids]
            + [oid for cid in chart_ids for oid in charts[cid].observation_ids]
        ))
        if any(oid not in obs_by_id for oid in obs_ids):
            continue
        observations = [obs_by_id[oid] for oid in obs_ids]
        analysis = single_metric_analysis(observations)
        if analysis is None or any(is_positive_topic_mismatch(o, slide) for o in observations):
            continue
        series = analysis.observations
        if not chart_ids:
            cid = stable_id("single-metric-chart", slide.id, *[o.id for o in series])
            chart = ChartPlan(
                id=cid, title=display_metric_name(series[0]), chart_type="line" if len(series) >= 3 else "bar",
                available_chart_types=["line", "bar"], question=slide.message,
                observation_ids=[o.id for o in series],
                source_pages=sorted({e.page for o in series for e in o.evidence}),
                x_metric=display_metric_name(series[0]), y_metric=display_metric_name(series[0]),
                x_axis_title="Period", y_axis_title=series[0].unit or "Value",
            )
            result.charts.append(chart)
            charts[cid] = chart
            slide.chart_ids = [cid]
        if slide.layout != "single_metric_hero":
            slide.layout = "single_metric_hero"
            enriched.append(slide.id)
        slide.source_pages = sorted(set(slide.source_pages) | {e.page for o in series for e in o.evidence})
    return enriched
