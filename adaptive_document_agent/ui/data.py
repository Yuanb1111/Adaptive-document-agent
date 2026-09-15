"""Extracted observation table."""

from adaptive_document_agent.models import PipelineResult


def render(st, result: PipelineResult) -> None:
    rows = []
    for item in result.observations:
        rows.append({
            "Metric": item.metric_canonical or item.metric_original,
            "Original Metric": item.metric_original,
            "Value": item.value,
            "Raw Value": item.raw_value,
            "Period": item.period,
            "Entity": item.entity,
            "Dimensions": item.dimensions,
            "Unit": item.unit,
            "Raw Unit": item.raw_unit,
            "Unit Scale": item.unit_scale,
            "Currency": item.currency,
            "Confidence": item.confidence,
            "Page": sorted({source.page for source in item.evidence}),
        })
    st.dataframe(rows, use_container_width=True)
