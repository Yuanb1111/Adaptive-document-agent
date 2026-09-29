"""Expose safe structural chart choices; never select an industry-specific storyline."""

from adaptive_document_agent.document_model import display_metric_name, period_sort_key
from adaptive_document_agent.models import ChartPlan
from adaptive_document_agent.utils.ids import stable_id

from .composition_data import composition_data, is_aggregate_category


def reported_composition_charts(index, *, maximum=3):
    candidates = []
    for metric in index.metrics():
        observations = index.for_metric(metric)
        dimensions = set().union(*[set(o.category_dimensions) | set(o.dimensions) for o in observations])
        dimensions -= {"table_context", "section", "period_basis", "column_role"}
        for dimension in sorted(dimensions):
            totals = [o for o in observations if is_aggregate_category(
                {**o.dimensions, **o.category_dimensions}.get(dimension, ""))]
            components = [o for o in observations if o not in totals]
            if not components:
                continue
            # Keep the whole matrix. Do not cherry-pick periods or omit unknown
            # categories simply to make the chart eligibility check pass.
            is_pct = all(o.unit in {"percent", "%", "percentage"} for o in observations)
            kind = ("stacked_percent" if is_pct else "stacked_bar") if len({o.period for o in observations}) > 1 else "doughnut"
            plan = ChartPlan(id=stable_id("composition", metric, dimension),
                title=display_metric_name(observations[0]), chart_type=kind,
                question=f"How does the reported {dimension} composition compare?",
                observation_ids=[o.id for o in components], total_observation_ids=[o.id for o in totals], series_dimension=dimension,
                x_dimension=dimension if kind == "doughnut" else None,
                source_pages=sorted({e.page for o in observations for e in o.evidence}),
                x_axis_title="Period" if kind != "doughnut" else dimension,
                y_axis_title="Share (%)" if is_pct else observations[0].currency or observations[0].unit or "Value")
            try:
                composition_data(plan, components, totals)
            except ValueError:
                continue
            plan.available_chart_types = [kind, "table"]
            candidates.append(plan)
            # Offer a clearly labelled single-period view only after the full
            # category matrix passed validation. The model can pair this with
            # the trend chart when the latest mix answers its selected question.
            if kind != "doughnut":
                latest = max((o.period for o in components), key=period_sort_key)
                snapshot = [o for o in components if o.period == latest]
                snapshot_totals = [o for o in totals if o.period == latest]
                ring = plan.model_copy(update={
                    "id": stable_id("composition", metric, dimension, latest),
                    "title": f"{plan.title} ({latest})",
                    "question": f"What is the reported {dimension} mix in {latest}?",
                    "chart_type": "doughnut", "available_chart_types": ["doughnut", "table"],
                    "observation_ids": [o.id for o in snapshot],
                    "total_observation_ids": [o.id for o in snapshot_totals],
                    "x_dimension": dimension, "x_axis_title": dimension,
                    "source_pages": sorted({e.page for o in [*snapshot, *snapshot_totals] for e in o.evidence}),
                })
                try:
                    composition_data(ring, snapshot, snapshot_totals)
                except ValueError:
                    continue
                candidates.append(ring)
    # Some extractors retain "row: column" measures rather than a category
    # dimension. The original table labels provide an equally explicit axis.
    from .source_row_composition import SOURCE_ROW, source_share_groups
    for key, views in source_share_groups(index.observations):
        totals = [o for o in views if is_aggregate_category(o.category_dimensions[SOURCE_ROW])]
        parts = [o for o in views if o not in totals]
        kind = "stacked_percent" if len({o.period for o in parts}) > 1 else "doughnut"
        contexts = {index.get(o.id).dimensions.get("table_context") for o in views}
        context = next(iter(contexts)) if len(contexts) == 1 else None
        title = f"{context} — {key[1]}" if context and context != key[0] else f"{key[1]} composition"
        plan = ChartPlan(
            id=stable_id("composition", *key), title=title,
            chart_type=kind, available_chart_types=[kind, "table"],
            question="How does the reported category mix compare?",
            series_dimension=SOURCE_ROW, composition_table_id=key[0],
            observation_ids=[o.id for o in parts], total_observation_ids=[o.id for o in totals],
            source_pages=sorted({e.page for o in views for e in o.evidence if e.table_id == key[0]}),
            x_axis_title="Period", y_axis_title="Share (%)",
        )
        try:
            composition_data(plan, [index.get(o.id) for o in parts], [index.get(o.id) for o in totals])
        except ValueError:
            continue
        candidates.append(plan)
        if kind != "doughnut":
            latest = max((o.period for o in parts), key=period_sort_key)
            candidates.append(plan.model_copy(update={
                "id": stable_id("composition", *key, latest), "title": f"{plan.title} ({latest})",
                "chart_type": "doughnut", "available_chart_types": ["doughnut", "pie", "table"],
                "observation_ids": [o.id for o in parts if o.period == latest],
                "total_observation_ids": [o.id for o in totals if o.period == latest],
                "x_dimension": SOURCE_ROW,
            }))
    # Amount matrices can show a percentage mix only if their retained totals
    # reconcile. Offer both views to semantic selection without normalising a
    # partial set into a fictitious whole.
    for plan in list(candidates):
        if plan.chart_type == "stacked_bar":
            normalized = plan.model_copy(update={
                "id": stable_id("composition_percent", plan.id),
                "chart_type": "stacked_percent", "available_chart_types": ["stacked_percent", "table"],
                "y_axis_title": "Share (%)",
            })
            try:
                composition_data(normalized, [index.get(o) for o in plan.observation_ids],
                                 [index.get(o) for o in plan.total_observation_ids])
            except ValueError:
                continue
            candidates.append(normalized)
        elif plan.chart_type == "doughnut":
            plan.available_chart_types = ["doughnut", "pie", "table"]
    return sorted(candidates, key=lambda c: (-len(c.observation_ids), c.id))[:maximum]


def presentation_compositions(index):
    """One evidence-complete visual choice per matrix or dated snapshot."""
    candidates = reported_composition_charts(index, maximum=max(3, len(index.observations) * 2))
    chosen = {}
    for chart in sorted(candidates, key=lambda c: (c.chart_type != "stacked_percent", c.id)):
        key = (frozenset(chart.observation_ids), frozenset(chart.total_observation_ids))
        if key in chosen:
            continue
        if chart.chart_type == "doughnut" and len(chart.observation_ids) <= 4:
            chart = chart.model_copy(update={"chart_type": "pie"})
        chosen[key] = chart
    return list(chosen.values())
