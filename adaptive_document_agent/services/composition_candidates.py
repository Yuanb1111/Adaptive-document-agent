"""Expose safe structural chart choices; never select an industry-specific storyline."""

from adaptive_document_agent.document_model import display_metric_name
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
    return sorted(candidates, key=lambda c: (-len(c.observation_ids), c.id))[:maximum]
