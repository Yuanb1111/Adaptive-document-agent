"""Native Office composition charts using the same validated matrix as the UI."""

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.util import Inches, Pt

from .composition_data import composition_data
from .presentation_style import FONT, semantic_color


def add_composition_chart(slide, plan, observations, bounds, *, totals=None, compact=False):
    from .pptx_export import _display_scale, _normalize_axis_ids, _rgb

    matrix = composition_data(plan, observations, totals)
    scale, scale_label = _display_scale(observations, max(v for row in matrix.values for v in row))
    data = CategoryChartData()
    share = plan.chart_type == "stacked_percent"
    doughnut = plan.chart_type == "doughnut"
    if doughnut:
        data.categories = matrix.categories
        data.add_series(plan.title, [row[0] / scale for row in matrix.values])
    else:
        data.categories = matrix.periods
        sums = [sum(row[i] for row in matrix.values) for i in range(len(matrix.periods))]
        for name, row in zip(matrix.categories, matrix.values):
            data.add_series(name, [v / sums[i] if share else v / scale for i, v in enumerate(row)])
    chart_type = {"stacked_bar": XL_CHART_TYPE.COLUMN_STACKED,
                  "stacked_percent": XL_CHART_TYPE.COLUMN_STACKED_100,
                  "doughnut": XL_CHART_TYPE.DOUGHNUT}[plan.chart_type]
    chart = slide.shapes.add_chart(chart_type, *(Inches(v) for v in bounds), data).chart
    _normalize_axis_ids(chart)
    chart.has_title = False
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    chart.legend.font.name = FONT
    chart.legend.font.size = Pt(10 if compact else 11)
    chart.chart_style = 10
    colors = getattr(slide, "_ada_colors", {})
    if doughnut:
        chart.plots[0].hole_size = 62
        for point, name in zip(chart.series[0].points, matrix.categories):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = _rgb(colors.get(name, semantic_color(name)))
    else:
        for series, name in zip(chart.series, matrix.categories):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = _rgb(colors.get(name, semantic_color(name)))
            series.format.line.fill.background()
        chart.value_axis.tick_labels.number_format = "0%" if share else "0.0"
        chart.value_axis.tick_labels.number_format_is_linked = False
        chart.value_axis.minimum_scale = 0
        if share:
            chart.value_axis.maximum_scale = 1
            chart.value_axis.major_unit = 0.25
        for axis in (chart.category_axis, chart.value_axis):
            axis.tick_labels.font.name = FONT
            axis.tick_labels.font.size = Pt(10 if compact else 11)
            axis.has_major_gridlines = False
    plot = chart.plots[0]
    plot.has_data_labels = plan.show_data_labels
    if plan.show_data_labels:
        labels = plot.data_labels
        labels.font.name = FONT
        labels.font.size = Pt(10 if compact else 11)
        labels.font.color.rgb = _rgb("FFFFFF")
        labels.font.bold = True
        labels.position = XL_DATA_LABEL_POSITION.CENTER
        labels.show_value = not doughnut
        labels.show_percentage = doughnut
        labels.number_format = "0.0%" if share or doughnut else "0.0"
        labels.number_format_is_linked = False
    return (1.0, "") if share else (scale, scale_label)
