"""Expose source amounts and the native renderer's scale to source reviewers."""


def chart_scale_evidence(chart, observations):
    from .composition_data import uses_composition_data
    from .pptx_export import _display_scale, _unit_label

    values = [o for o in observations if o.id in chart.observation_ids and o.value is not None]
    record = dict(chart_id=chart.id, source_values=[dict(
        observation_id=o.id, period=o.period, raw_value=o.raw_value,
        raw_unit=o.raw_unit, source_unit_scale=o.unit_scale,
        normalized_value=o.value, normalized_unit=o.unit, currency=o.currency,
    ) for o in values])
    if (not values or uses_composition_data(chart)
            or chart.chart_type not in {'line', 'bar', 'horizontal_bar', 'area'}):
        return record
    divisor, scale = _display_scale(values, max(abs(float(o.value)) for o in values), prefer_source=True)
    record['native_ppt_scale'] = dict(
        divisor=divisor, visible_unit=_unit_label(values, scale),
        values=[dict(observation_id=o.id, value=float(o.value) / divisor) for o in values],
        status='renderer inputs; final exported geometry and labels require export validation',
    )
    record['web_chart_values'] = 'normalized_value, not raw_value; ChartPlan axis titles describe these base units'
    return record
