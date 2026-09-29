"""Native Office composition charts using the same validated matrix as the UI."""

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from .composition_data import composition_data
from .fourier_brand import ALL_CHART_COLORS, BORDER, MUTED, TEXT, label_color
from .presentation_style import (
    FONT, chart_color, deck_color_map, normalize_chart_color_map,
)


def _composition_colors(slide, categories):
    """Keep deck assignments; repair stale maps once over their complete keys."""
    incoming = dict(getattr(slide, "_ada_colors", {}))
    if not incoming:
        return deck_color_map(categories)
    if any(value not in ALL_CHART_COLORS for value in incoming.values()):
        colors = deck_color_map([*incoming, *categories])
        colors.update(incoming)
        colors = normalize_chart_color_map(colors)
        slide._ada_colors = colors
        return colors
    return incoming


def _style_labels(labels, *, share, doughnut, compact, color):
    """Specify label content as well as style when overriding series defaults."""
    from .pptx_export import _rgb

    labels.font.name = FONT
    labels.font.size = Pt(10 if compact else 11)
    labels.font.color.rgb = _rgb(color)
    labels.font.bold = True
    labels.position = XL_DATA_LABEL_POSITION.CENTER
    labels.show_value = not doughnut
    labels.show_percentage = doughnut
    labels.number_format = "0.0%" if share or doughnut else "0.0"
    labels.number_format_is_linked = False


def add_composition_chart(slide, plan, observations, bounds, *, totals=None, compact=False):
    from .pptx_export import _display_scale, _normalize_axis_ids, _rgb

    matrix = composition_data(plan, observations, totals)
    scale, scale_label = _display_scale(observations, max(v for row in matrix.values for v in row))
    data = CategoryChartData()
    share = plan.chart_type == "stacked_percent"
    doughnut = plan.chart_type in {"doughnut", "pie"}
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
                  "pie": XL_CHART_TYPE.PIE,
                  "doughnut": XL_CHART_TYPE.DOUGHNUT}[plan.chart_type]
    chart = slide.shapes.add_chart(chart_type, *(Inches(v) for v in bounds), data).chart
    _normalize_axis_ids(chart)
    chart.has_title = False
    chart.chart_style = None
    chart.font.name = FONT
    chart.font.size = Pt(10 if compact else 11)
    chart.font.color.rgb = _rgb(MUTED)
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    chart.legend.font.name = FONT
    chart.legend.font.size = Pt(10 if compact else 11)
    chart.legend.font.color.rgb = _rgb(MUTED)
    colors = _composition_colors(slide, matrix.categories)
    if doughnut:
        if plan.chart_type == "doughnut":
            chart.plots[0].hole_size = 62
        series = chart.series[0]
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = _rgb(chart_color(matrix.categories[0], colors))
        series.format.line.fill.background()
        for point, name in zip(chart.series[0].points, matrix.categories):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = _rgb(chart_color(name, colors))
            point.format.line.fill.background()
    else:
        for series, name in zip(chart.series, matrix.categories):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = _rgb(chart_color(name, colors))
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
            axis.tick_labels.font.color.rgb = _rgb(MUTED)
            axis.format.line.color.rgb = _rgb(BORDER)
            axis.has_major_gridlines = False
    plot = chart.plots[0]
    # Thin pie slices use outside labels. For stacked charts, hide only labels
    # that cannot fit their segment; all source values remain in the workbook.
    column_totals = [sum(row[i] for row in matrix.values) for i in range(len(matrix.periods))]
    labels_fit = all(v / column_totals[i] >= .06 for row in matrix.values for i, v in enumerate(row))
    outside = doughnut and not labels_fit
    plot.has_data_labels = plan.show_data_labels
    if plot.has_data_labels:
        _style_labels(plot.data_labels, share=share, doughnut=doughnut, compact=compact, color=TEXT)
        for series, name in zip(chart.series, matrix.categories):
            _style_labels(series.data_labels, share=share, doughnut=doughnut, compact=compact,
                          color=label_color(chart_color(name, colors)))
        if outside:
            plot.data_labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
            chart.series[0].data_labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
            if not compact:
                chart.legend.position = XL_LEGEND_POSITION.RIGHT
        if not doughnut and not labels_fit:
            for series, row in zip(chart.series, matrix.values):
                for i, value in enumerate(row):
                    if value / column_totals[i] < .06:
                        label = series.points[i].data_label
                        # A deleted point label cannot also carry the styling
                        # and content nodes python-pptx adds. Office repairs
                        # that invalid combination on open. Hide its content
                        # explicitly while keeping the native chart editable.
                        label._get_or_add_dLbl()
                        for tag in ("showVal", "showPercent", "showCatName", "showSerName"):
                            flags = label._dLbl.xpath(f"c:{tag}")
                            flag = flags[0] if flags else OxmlElement(f"c:{tag}")
                            flag.set("val", "0")
                            if not flags:
                                label._dLbl.append(flag)
        if doughnut:
            for point, name in zip(chart.series[0].points, matrix.categories):
                label = point.data_label
                label.font.name = FONT
                label.font.size = Pt(10 if compact else 11)
                label.font.bold = True
                label.font.color.rgb = _rgb(TEXT if outside else label_color(chart_color(name, colors)))
                if outside:
                    label.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
                number_format = OxmlElement("c:numFmt")
                number_format.set("formatCode", "0.0%")
                number_format.set("sourceLinked", "0")
                label._dLbl.insert(1, number_format)
                # Custom point labels default to values in python-pptx. Keep
                # the percentage semantics of the editable doughnut chart.
                for tag, value in (("showVal", "0"), ("showPercent", "1")):
                    elements = label._dLbl.xpath(f"c:{tag}")
                    element = elements[0] if elements else OxmlElement(f"c:{tag}")
                    element.set("val", value)
                    if not elements:
                        label._dLbl.append(element)
    return (1.0, "") if share else (scale, scale_label)
