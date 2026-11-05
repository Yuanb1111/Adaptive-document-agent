"""Separate neighboring native column labels without removing values."""


def separate_close_column_labels(chart, *, width):
    from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION
    if chart.chart_type != XL_CHART_TYPE.COLUMN_CLUSTERED or len(chart.series) != 1 or width >= 9:
        return
    series = chart.series[0]
    values = list(series.values)
    if len(values) < 4 or any(v is None for v in values):
        return
    peak = max(abs(v) for v in values)
    if peak <= 0:
        return
    # Similar-height labels crowd when a renderer infers calendar spacing for
    # categorical interim dates. Bind labels to every actual category point.
    close = any(values[i] > 0 and values[i-1] > 0
                and abs(values[i] - values[i-1]) < peak * .08 for i in range(1, len(values)))
    if not close:
        return
    style = chart.plots[0].data_labels
    pattern = style.number_format.split(';')[0]
    digits = pattern.split('.', 1)[1].count('0') if '.' in pattern else 0
    # Explicit overrides must cover every point: some renderers otherwise
    # display only the overridden labels or infer calendar positions from
    # categorical date strings. Keep all labels outside their columns: a long
    # amount need not fit inside a narrow bar. Preserve size and precision.
    for point, value in zip(series.points, values, strict=True):
        label = point.data_label
        label.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        color = style.font.color.rgb
        label.font.color.rgb = color
        label.text_frame.text = f'{value:,.{digits}f}'
        for paragraph in label.text_frame.paragraphs:
            paragraph.font.size = style.font.size
            for run in paragraph.runs:
                run.font.name, run.font.size = style.font.name, style.font.size
                run.font.bold, run.font.color.rgb = style.font.bold, color
