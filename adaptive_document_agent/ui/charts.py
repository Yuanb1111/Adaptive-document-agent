"""Plotly rendering with visible labels, explicit units, and paired provenance."""

from __future__ import annotations

from typing import Any

from adaptive_document_agent.document_model import DocumentIndex, paired_observations, period_sort_key
from adaptive_document_agent.models import ChartPlan, ChartType, Observation


def chart_rows(plan: ChartPlan, index: DocumentIndex) -> list[dict[str, Any]]:
    """Build the exact, reviewable data rows used by a chart."""
    observations = [index.get(identifier) for identifier in plan.observation_ids]
    values = [item for item in observations if item and item.value is not None]
    if plan.chart_type == "scatter" and plan.x_metric and plan.y_metric:
        rows: list[dict[str, Any]] = []
        for left, right in paired_observations(values, plan.x_metric, plan.y_metric):
            rows.append(
                {
                    "Label": _context_label(left),
                    "X Metric": left.metric_canonical or left.metric_original,
                    "X Value": float(left.value),
                    "X Display": _display_value(left),
                    "Y Metric": right.metric_canonical or right.metric_original,
                    "Y Value": float(right.value),
                    "Y Display": _display_value(right),
                    "Source pages": _source_pages([left, right]),
                }
            )
        return rows

    rows = []
    for item in sorted(values, key=lambda observation: period_sort_key(observation.period)):
        dimensions = {**item.dimensions, **item.category_dimensions}
        label = dimensions.get(plan.x_dimension) if plan.x_dimension else None
        label = label or item.period or next(iter(item.dimensions.values()), item.entity or item.metric_original)
        series = item.period if plan.x_dimension and item.period else item.entity
        if plan.series_dimension:
            series = dimensions.get(plan.series_dimension)
        rows.append(
            {
                "Label": str(label),
                "Series": series or "",
                "Metric": item.metric_canonical or item.metric_original,
                "Value": float(item.value),
                "Display": _display_value(item),
                "Unit": item.unit or "",
                "Currency": item.currency or "",
                "Source pages": _source_pages([item]),
            }
        )
    return rows


def render_chart(
    plan: ChartPlan,
    index: DocumentIndex,
    *,
    chart_type: ChartType | None = None,
    show_data_labels: bool | None = None,
):
    """Render a compatible view while keeping all important values visible."""
    import plotly.express as px
    import plotly.graph_objects as go

    selected = chart_type or plan.chart_type
    if selected not in (plan.available_chart_types or [plan.chart_type]):
        raise ValueError(f"Chart type '{selected}' is not compatible with this analysis.")
    from adaptive_document_agent.services.composition_data import COMPOSITION_TYPES, composition_data
    if selected in COMPOSITION_TYPES:
        from adaptive_document_agent.services.presentation_style import deck_color_map
        values = [index.get(oid) for oid in plan.observation_ids if index.get(oid)]
        totals = [index.get(oid) for oid in plan.total_observation_ids if index.get(oid)]
        matrix = composition_data(plan.model_copy(update={"chart_type": selected}), values, totals)
        colors = deck_color_map(matrix.categories)
        enabled = plan.show_data_labels if show_data_labels is None else show_data_labels
        if selected == "doughnut":
            figure = go.Figure(go.Pie(labels=matrix.categories, values=[r[0] for r in matrix.values], hole=0.62,
                marker_colors=["#" + colors[c] for c in matrix.categories], sort=False,
                textinfo="label+percent" if enabled else "none"))
        else:
            sums = [sum(row[i] for row in matrix.values) for i in range(len(matrix.periods))]
            figure = go.Figure()
            for category, row in zip(matrix.categories, matrix.values):
                y = [100 * v / sums[i] for i, v in enumerate(row)] if selected == "stacked_percent" else row
                figure.add_bar(name=category, x=matrix.periods, y=y, marker_color="#" + colors[category],
                    text=[f"{v:.1f}%" if selected == "stacked_percent" else f"{v:g}" for v in y] if enabled else None,
                    textposition="inside", customdata=row,
                    hovertemplate="%{x}<br>%{y}<br>Source value: %{customdata}<extra>%{fullData.name}</extra>")
            figure.update_layout(barmode="stack", yaxis_title="Share (%)" if selected == "stacked_percent" else plan.y_axis_title)
            if selected == "stacked_percent":
                figure.update_yaxes(range=[0, 100], ticksuffix="%")
        figure.update_layout(title=plan.title, font_family="Arial")
        figure.add_annotation(text="Source pages: " + ", ".join(map(str, matrix.source_pages)),
            xref="paper", yref="paper", x=0, y=-0.2, showarrow=False)
        return figure
    rows = chart_rows(plan, index)
    labels_enabled = plan.show_data_labels if show_data_labels is None else show_data_labels
    if not rows:
        return go.Figure().update_layout(title=plan.title)
    if selected == "table":
        columns = list(rows[0])
        figure = go.Figure(
            data=[
                go.Table(
                    header={"values": [f"<b>{column}</b>" for column in columns], "fill_color": "#E8EEF7", "align": "left"},
                    cells={"values": [[row[column] for row in rows] for column in columns], "align": "left"},
                )
            ]
        )
        return figure.update_layout(title=plan.title, margin={"l": 20, "r": 20, "t": 70, "b": 20})
    if selected == "scatter":
        figure = px.scatter(
            rows,
            x="X Value",
            y="Y Value",
            text="Label" if labels_enabled else None,
            title=plan.title,
            labels={"X Value": plan.x_axis_title, "Y Value": plan.y_axis_title},
            custom_data=["X Display", "Y Display", "Source pages"],
        )
        figure.update_traces(
            textposition="top center",
            marker={"size": 10},
            hovertemplate=(
                "%{text}<br>" + plan.x_axis_title + ": %{customdata[0]}<br>" + plan.y_axis_title + ": %{customdata[1]}"
                + "<br>Source pages: %{customdata[2]}<extra></extra>"
            ),
        )
        return _finish(figure, plan)

    color = "Series" if any(row["Series"] for row in rows) and len({row["Series"] for row in rows}) > 1 else None
    text = "Display" if labels_enabled else None
    common = {
        "data_frame": rows,
        "x": "Label",
        "y": "Value",
        "color": color,
        "text": text,
        "title": plan.title,
        "labels": {"Label": plan.x_axis_title, "Value": plan.y_axis_title, "Series": "Series"},
        "custom_data": ["Display", "Source pages"],
    }
    if selected == "line":
        figure = px.line(**common, markers=True)
        figure.update_traces(textposition="top center")
    elif selected == "area":
        figure = px.area(**common, markers=True)
        figure.update_traces(textposition="top center")
    elif selected == "horizontal_bar":
        horizontal = dict(common)
        horizontal.update({"x": "Value", "y": "Label", "orientation": "h", "labels": {"Label": plan.x_axis_title, "Value": plan.y_axis_title}})
        figure = px.bar(**horizontal)
        figure.update_traces(textposition="outside")
    elif selected == "pie":
        figure = px.pie(rows, names="Label", values="Value", title=plan.title, custom_data=["Display", "Source pages"])
        figure.update_traces(textinfo="label+percent+value" if labels_enabled else "percent", textposition="auto")
    else:
        figure = px.bar(**common, barmode="group")
        figure.update_traces(textposition="outside")
    return _finish(figure, plan, categorical=selected != "horizontal_bar")


def _finish(figure, plan: ChartPlan, *, categorical: bool = False):
    figure.update_layout(
        xaxis_title=plan.x_axis_title,
        yaxis_title=plan.y_axis_title,
        legend_title_text="Series",
        margin={"l": 40, "r": 30, "t": 80, "b": 60},
        uniformtext_minsize=9,
        uniformtext_mode="hide",
    )
    if categorical:
        figure.update_xaxes(type="category")
    return figure


def _context_label(item: Observation) -> str:
    parts = [item.period, item.entity, *item.dimensions.values()]
    return " · ".join(str(part) for part in parts if part) or "Matched observation"


def _source_pages(items: list[Observation]) -> str:
    return ", ".join(map(str, sorted({source.page for item in items for source in item.evidence})))


def _display_value(item: Observation) -> str:
    value = float(item.value or 0)
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        number = f"{value / 1_000_000_000:.2f}B"
    elif absolute >= 1_000_000:
        number = f"{value / 1_000_000:.2f}M"
    elif absolute >= 1_000:
        number = f"{value / 1_000:.2f}K"
    elif absolute >= 100:
        number = f"{value:,.1f}"
    else:
        number = f"{value:,.2f}".rstrip("0").rstrip(".")
    if item.currency:
        return f"{item.currency} {number}"
    if item.unit == "percent":
        return f"{number}%"
    return f"{number} {item.unit}".strip() if item.unit else number
