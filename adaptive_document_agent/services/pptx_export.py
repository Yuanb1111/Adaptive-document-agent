"""Editable, presentation-ready PowerPoint export for analysis results."""

from __future__ import annotations

import io
from collections import defaultdict
from typing import Any, Iterable

from adaptive_document_agent.document_model import DocumentIndex, metric_key, metric_label, paired_observations, period_sort_key
from adaptive_document_agent.models import ChartPlan, Observation, PipelineResult


SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5
NAVY = "142442"
MIDNIGHT = "08162F"
INK = "1B2A41"
MUTED = "617083"
BLUE = "0874E8"
TEAL = "13A6B8"
VIOLET = "7A3FF2"
AMBER = "F2B544"
CORAL = "E9634C"
WHITE = "FFFFFF"
IVORY = "F3F2EA"
STONE = "D8D6CA"
FONT = "Aptos"
TITLE_FONT = "Aptos Display"


def build_presentation(result: PipelineResult) -> bytes:
    """Return a widescreen PPTX with editable charts, tables, and text."""
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError as exc:  # pragma: no cover - deployment configuration failure
        raise RuntimeError("PowerPoint export requires python-pptx.") from exc

    presentation = Presentation()
    presentation.slide_width = Inches(SLIDE_WIDTH)
    presentation.slide_height = Inches(SLIDE_HEIGHT)

    _add_cover(presentation, result)
    _add_evidence_overview(presentation, result)
    index = DocumentIndex(result.observations)
    usable_charts = _usable_charts(result)
    for ordinal, plan in enumerate(usable_charts[:8]):
        _add_chart_slide(presentation, plan, index, ordinal=ordinal)
    if not usable_charts:
        _add_no_chart_slide(presentation, result)
    _add_findings_slide(presentation, result)
    _add_quality_slide(presentation, result)
    _add_evidence_table_slide(presentation, result)
    _number_slides(presentation)

    stream = io.BytesIO()
    presentation.save(stream)
    return stream.getvalue()


def _add_cover(presentation: Any, result: PipelineResult) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _background(slide, MIDNIGHT)
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(4.55), Inches(0.13))
    _solid_shape(accent, BLUE)
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(4.55), Inches(0), Inches(2.35), Inches(0.13))
    _solid_shape(accent, TEAL)
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(6.9), Inches(0), Inches(1.25), Inches(0.13))
    _solid_shape(accent, VIOLET)
    _text(slide, "DOCUMENT INTELLIGENCE", 0.78, 0.62, 4.4, 0.28, size=12, color=TEAL, bold=True)
    _text(slide, f"{result.document.page_count:03d}", 9.25, 0.48, 3.3, 1.25, size=62, color="263958", bold=True, font=TITLE_FONT, align="right")
    title = result.report_plan.title or "Adaptive Document Analysis"
    _text(slide, title, 0.78, 1.45, 11.25, 1.55, size=38, color=WHITE, bold=True, font=TITLE_FONT)
    _text(slide, result.profile.document_type, 0.8, 3.2, 8.8, 0.45, size=18, color="A9C7E4", bold=True)
    purpose = _summary_text(result.profile.document_purpose, 300)
    _text(slide, purpose, 0.8, 3.78, 10.8, 1.3, size=18, color=WHITE)
    ranges = _page_ranges(result)
    _rule(slide, 0.8, 6.05, 11.75, 0.012, "344B6D")
    _text(slide, f"Analysis scope  {ranges}", 0.8, 6.28, 5.8, 0.35, size=12, color="A9C7E4")
    _text(slide, "Evidence-grounded presentation", 8.15, 6.28, 4.4, 0.35, size=12, color="A9C7E4", align="right")


def _add_evidence_overview(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Analysis at a glance", "The retained evidence and current analytical scope", background=IVORY)
    metrics = {
        metric_key(item)
        for item in result.observations
        if metric_key(item) not in {"page", "pages"}
    }
    source_pages = {source.page for item in result.observations for source in item.evidence}
    values = [
        (str(len(result.observations)), "retained facts"),
        (str(len(metrics)), "distinct metrics"),
        (str(len(result.charts)), "validated charts"),
        (str(len(source_pages)), "evidence pages"),
    ]
    colors = (BLUE, TEAL, VIOLET, CORAL)
    for index, (value, label) in enumerate(values):
        left = 0.75 + index * 3.08
        _text(slide, value, left, 1.68, 2.45, 0.8, size=36, color=colors[index], bold=True, font=TITLE_FONT)
        _text(slide, label, left, 2.46, 2.45, 0.4, size=15, color=INK, bold=True)
        if index < len(values) - 1:
            _rule(slide, left + 2.55, 1.72, 0.018, 1.15, STONE)
    _rule(slide, 0.75, 3.12, 11.85, 0.018, STONE)
    _text(slide, "Document purpose", 0.75, 3.48, 2.6, 0.35, size=14, color=BLUE, bold=True)
    _text(slide, _summary_text(result.profile.document_purpose, 460), 0.75, 3.9, 7.55, 1.55, size=19, color=INK, bold=True)
    focus = _summary_text(result.profile.analysis_focus or "Automatic discovery", 280)
    _text(slide, "Analysis focus", 9.05, 3.48, 2.8, 0.35, size=14, color=VIOLET, bold=True)
    _text(slide, focus, 9.05, 3.9, 3.15, 1.42, size=17, color=INK)
    _text(slide, f"Pages reviewed  { _page_ranges(result) }", 9.05, 5.55, 3.15, 0.4, size=13, color=MUTED)


def _add_chart_slide(presentation: Any, plan: ChartPlan, index: DocumentIndex, *, ordinal: int) -> None:
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    observations = [index.get(identifier) for identifier in plan.observation_ids]
    values = [item for item in observations if item and item.value is not None]
    title = _presentation_chart_title(plan.title, values)
    layout = ordinal % 3
    if layout == 0:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        _background(slide, MIDNIGHT)
        _text(slide, "ANALYSIS", 0.72, 0.48, 2.0, 0.28, size=11, color=TEAL, bold=True)
        _text(slide, title, 0.72, 1.03, 4.0, 1.18, size=29, color=WHITE, bold=True, font=TITLE_FONT)
        _text(slide, _summary_text(plan.question, 180), 0.74, 2.36, 3.85, 1.05, size=15, color="BBD0E6")
        chart_box = (4.72, 0.7, 7.9, 5.92)
        _panel(slide, *chart_box, fill=WHITE)
        chart_bounds = (5.02, 1.05, 7.3, 5.05)
    elif layout == 1:
        slide = _base_slide(presentation, title, background=IVORY)
        chart_bounds = (0.72, 1.45, 8.35, 5.15)
        _text(slide, "KEY MOVEMENT", 9.45, 1.62, 2.6, 0.28, size=11, color=VIOLET, bold=True)
        _rule(slide, 9.43, 2.02, 2.9, 0.02, STONE)
    else:
        slide = _base_slide(presentation, title, _summary_text(plan.question, 150), background=WHITE)
        chart_bounds = (0.72, 1.58, 11.85, 4.82)
    if not values:
        _text(slide, "The chart plan contains no usable values.", 0.85, 2.4, 11.4, 0.8, size=22, color=MUTED, align="center")
        return

    max_abs = max(abs(float(item.value or 0)) for item in values)
    scale, scale_label = _display_scale(values, max_abs)
    chart_left, chart_top, chart_width, chart_height = (Inches(value) for value in chart_bounds)

    if plan.chart_type == "scatter" and plan.x_metric and plan.y_metric:
        data = XyChartData()
        series = data.add_series("Observed pairs")
        for left, right in paired_observations(values, plan.x_metric, plan.y_metric):
            series.add_data_point(float(left.value or 0) / scale, float(right.value or 0) / scale)
        chart = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, chart_left, chart_top, chart_width, chart_height, data).chart
    else:
        rows = _series_rows(plan, values)
        categories = list(dict.fromkeys(row[0] for row in rows))
        series_names = list(dict.fromkeys(row[1] for row in rows))
        data = CategoryChartData()
        data.categories = categories
        for name in series_names:
            lookup = {label: value for label, series_name, value in rows if series_name == name}
            data.add_series(name, [lookup.get(label) / scale if lookup.get(label) is not None else None for label in categories])
        chart_type = {
            "line": XL_CHART_TYPE.LINE_MARKERS,
            "area": XL_CHART_TYPE.AREA,
            "pie": XL_CHART_TYPE.PIE,
            "horizontal_bar": XL_CHART_TYPE.BAR_CLUSTERED,
        }.get(plan.chart_type, XL_CHART_TYPE.COLUMN_CLUSTERED)
        chart = slide.shapes.add_chart(chart_type, chart_left, chart_top, chart_width, chart_height, data).chart

    chart.has_title = False
    _normalize_axis_ids(chart)
    chart.has_legend = len(getattr(chart, "series", [])) > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.font.name = FONT
        chart.legend.font.size = Pt(11)
    chart.chart_style = 10
    for series_index, series in enumerate(chart.series):
        color = (BLUE, TEAL, VIOLET, CORAL)[series_index % 4]
        try:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = _rgb(color)
            series.format.line.color.rgb = _rgb(color)
        except (AttributeError, ValueError):
            pass
    try:
        chart.plots[0].has_data_labels = True
        labels = chart.plots[0].data_labels
        if plan.chart_type == "pie":
            labels.position = XL_DATA_LABEL_POSITION.BEST_FIT
        elif plan.chart_type in {"line", "area"}:
            labels.position = XL_DATA_LABEL_POSITION.ABOVE
        else:
            labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END
        labels.font.name = FONT
        labels.font.size = Pt(11)
        labels.number_format = "0.0"
    except (AttributeError, ValueError):
        pass
    try:
        chart.category_axis.tick_labels.font.name = FONT
        chart.category_axis.tick_labels.font.size = Pt(11)
        chart.value_axis.tick_labels.font.name = FONT
        chart.value_axis.tick_labels.font.size = Pt(10)
        chart.value_axis.has_major_gridlines = True
        chart.value_axis.axis_title.text_frame.paragraphs[0].text = ""
    except (AttributeError, ValueError):
        pass

    unit = _unit_label(values, scale_label)
    pages = ", ".join(map(str, plan.source_pages)) or "not available"
    movement = _change_summary(values, scale)
    if layout == 0:
        if movement:
            _text(slide, movement[0], 0.72, 4.1, 3.9, 0.8, size=30, color=AMBER, bold=True, font=TITLE_FONT)
            _text(slide, movement[1], 0.74, 4.92, 3.82, 0.72, size=14, color=WHITE)
        _text(slide, unit, 0.74, 6.25, 3.4, 0.3, size=11, color="9CB6D0")
        _text(slide, f"Source pages  {pages}", 8.25, 6.83, 4.35, 0.25, size=10, color="9CB6D0", align="right")
    elif layout == 1:
        if movement:
            _text(slide, movement[0], 9.42, 2.35, 3.0, 0.82, size=31, color=VIOLET, bold=True, font=TITLE_FONT)
            _text(slide, movement[1], 9.44, 3.2, 2.85, 1.05, size=15, color=INK)
        else:
            _text(slide, f"{len(values)}", 9.42, 2.35, 3.0, 0.82, size=31, color=VIOLET, bold=True, font=TITLE_FONT)
            _text(slide, "comparable reported observations", 9.44, 3.2, 2.85, 0.72, size=15, color=INK)
        _text(slide, unit, 9.44, 5.2, 2.85, 0.35, size=12, color=MUTED)
        _text(slide, f"Source pages  {pages}", 9.44, 5.72, 2.85, 0.55, size=11, color=MUTED)
    else:
        _text(slide, unit, 0.76, 6.48, 5.4, 0.35, size=11, color=MUTED)
        if movement:
            _text(slide, f"{movement[0]}  {movement[1]}", 4.0, 6.43, 5.7, 0.42, size=13, color=BLUE, bold=True, align="center")
        _text(slide, f"Source pages  {pages}", 9.2, 6.48, 3.35, 0.35, size=11, color=MUTED, align="right")


def _add_no_chart_slide(presentation: Any, result: PipelineResult) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _background(slide, MIDNIGHT)
    _text(slide, "0", 0.72, 0.85, 3.2, 1.5, size=72, color=TEAL, bold=True, font=TITLE_FONT)
    _text(slide, "No chart passed the evidence checks", 3.25, 1.18, 8.7, 0.9, size=30, color=WHITE, bold=True, font=TITLE_FONT)
    _text(
        slide,
        "The presentation preserves this outcome instead of drawing unsupported comparisons. Review the extracted periods, units and validation warnings before using the data for decisions.",
        3.27,
        2.45,
        8.6,
        1.55,
        size=18,
        color="BBD0E6",
    )
    _rule(slide, 3.27, 4.45, 8.6, 0.015, "344B6D")
    _text(slide, f"{len(result.observations)} retained observations remain available in the evidence appendix", 3.27, 4.75, 8.6, 0.55, size=16, color=AMBER, bold=True)


def _add_findings_slide(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Key findings", "Evidence-backed conclusions from the analysis", background=IVORY)
    findings = sorted(result.insights, key=lambda item: (item.importance, item.confidence), reverse=True)[:4]
    if not findings:
        _text(slide, "No validated analytical findings were produced.", 0.9, 2.4, 11.4, 0.8, size=22, color=MUTED, align="center")
        return
    top = 1.48
    colors = (BLUE, TEAL, VIOLET, CORAL)
    for number, finding in enumerate(findings, start=1):
        color = colors[(number - 1) % len(colors)]
        _text(slide, f"{number:02d}", 0.76, top, 0.62, 0.45, size=16, color=color, bold=True)
        _text(slide, _summary_text(finding.title, 130), 1.48, top - 0.02, 3.95, 0.68, size=18, color=INK, bold=True)
        pages = sorted({source.page for source in finding.evidence})
        source = f"Pages {', '.join(map(str, pages))}" if pages else "Calculated from retained evidence"
        _text(slide, _summary_text(finding.narrative, 330), 5.58, top - 0.01, 5.65, 0.92, size=15, color=INK)
        _text(slide, source, 11.25, top + 0.02, 1.2, 0.55, size=9, color=MUTED, align="right")
        _rule(slide, 1.48, top + 1.05, 10.98, 0.012, STONE)
        top += 1.25


def _add_quality_slide(presentation: Any, result: PipelineResult) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _background(slide, NAVY)
    _text(slide, "DATA QUALITY", 0.75, 0.55, 2.8, 0.3, size=11, color=AMBER, bold=True)
    _text(slide, "Limits that affect interpretation", 0.75, 1.02, 8.9, 0.75, size=31, color=WHITE, bold=True, font=TITLE_FONT)
    messages = list(dict.fromkeys([
        *result.profile.data_quality_notes,
        *(warning.message for warning in result.validation_warnings if warning.severity in {"error", "warning"}),
    ]))[:5]
    if not messages:
        messages = ["No material data-quality warning was retained for this analysis."]
    top = 2.08
    for index, message in enumerate(messages, start=1):
        _text(slide, f"{index:02d}", 0.78, top, 0.55, 0.38, size=14, color=AMBER, bold=True)
        _text(slide, _summary_text(message, 360), 1.5, top - 0.03, 10.55, 0.78, size=16, color=WHITE)
        _rule(slide, 1.5, top + 0.77, 10.65, 0.01, "3B506D")
        top += 0.93


def _add_evidence_table_slide(presentation: Any, result: PipelineResult) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    slide = _base_slide(presentation, "Evidence appendix", "Selected reported values with page-level provenance", background=IVORY)
    observations = _representative_observations(result, maximum=9)
    headers = ["Metric", "Period", "Reported value", "Unit", "Page"]
    rows = [
        [
            _summary_text(metric_label(item), 58),
            item.period or "-",
            item.raw_value,
            "percent" if item.unit == "percent" else item.raw_unit or _unit_label([item], ""),
            ", ".join(map(str, sorted({source.page for source in item.evidence}))),
        ]
        for item in observations
    ]
    table_shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(0.72), Inches(1.55), Inches(11.9), Inches(4.95))
    table = table_shape.table
    widths = [4.55, 1.28, 2.05, 2.7, 0.95]
    for column, width in zip(table.columns, widths):
        column.width = Inches(width)
    for column, header in enumerate(headers):
        cell = table.cell(0, column)
        cell.text = header
        _cell_style(cell, fill=NAVY, color=WHITE, bold=True, size=12)
    for row_index, values in enumerate(rows, start=1):
        for column, value in enumerate(values):
            cell = table.cell(row_index, column)
            cell.text = str(value)
            _cell_style(cell, fill=WHITE if row_index % 2 else "E9E8DF", color=INK, bold=False, size=11)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT if column in {2, 4} else PP_ALIGN.LEFT
    for row in table.rows:
        row.height = Inches(0.47)
    _text(slide, "The JSON and CSV exports contain the complete retained fact base.", 0.76, 6.72, 11.75, 0.28, size=10, color=MUTED)


def _base_slide(presentation: Any, title: str, subtitle: str = "", *, background: str = WHITE) -> Any:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _background(slide, background)
    _text(slide, title, 0.72, 0.34, 11.7, 0.66, size=29, color=NAVY, bold=True, font=TITLE_FONT)
    if subtitle:
        _text(slide, subtitle, 0.74, 1.02, 11.4, 0.3, size=12, color=MUTED)
    _rule(slide, 0.72, 1.31, 11.9, 0.025, BLUE)
    return slide


def _text(
    slide: Any,
    value: str,
    left: float,
    top: float,
    width: float,
    height: float,
    *,
    size: float,
    color: str,
    bold: bool = False,
    font: str = FONT,
    align: str = "left",
) -> Any:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.02)
    frame.margin_top = frame.margin_bottom = Inches(0.01)
    frame.vertical_anchor = MSO_ANCHOR.TOP
    paragraph = frame.paragraphs[0]
    paragraph.text = value
    paragraph.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
    paragraph.font.name = font
    paragraph.font.size = Pt(size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = _rgb(color)
    return box


def _rule(slide: Any, left: float, top: float, width: float, height: float, color: str) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    _solid_shape(shape, color)


def _panel(slide: Any, left: float, top: float, width: float, height: float, *, fill: str) -> Any:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    _solid_shape(shape, fill)
    return shape


def _solid_shape(shape: Any, color: str) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(color)
    shape.line.fill.background()


def _background(slide: Any, color: str) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(color)


def _rgb(value: str) -> Any:
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(value)


def _normalize_axis_ids(chart: Any) -> None:
    """Keep chart axis IDs portable across strict OOXML readers."""
    for element in chart._chartSpace.iter():
        if element.tag.rsplit("}", 1)[-1] not in {"axId", "crossAx"}:
            continue
        value = element.get("val")
        if value and value.startswith("-"):
            element.set("val", str(abs(int(value))))


def _series_rows(plan: ChartPlan, observations: list[Observation]) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []
    for item in sorted(observations, key=lambda value: period_sort_key(value.period)):
        label = item.dimensions.get(plan.x_dimension) if plan.x_dimension else None
        label = label or item.period or next(iter(item.dimensions.values()), item.entity or item.metric_original)
        series = item.entity or metric_label(item)
        rows.append((str(label), str(series), float(item.value or 0)))
    return rows


def _display_scale(observations: list[Observation], maximum: float) -> tuple[float, str]:
    if any(item.unit == "percent" for item in observations):
        return 1.0, ""
    if maximum >= 1_000_000_000:
        return 1_000_000_000.0, "billions"
    if maximum >= 1_000_000:
        return 1_000_000.0, "millions"
    if maximum >= 1_000:
        return 1_000.0, "thousands"
    return 1.0, ""


def _unit_label(observations: Iterable[Observation], scale_label: str) -> str:
    values = list(observations)
    currencies = sorted({item.currency for item in values if item.currency})
    units = sorted({item.unit for item in values if item.unit and item.unit != "currency"})
    parts = [*currencies, *units]
    if scale_label:
        parts.append(scale_label)
    return " / ".join(parts) or "Reported value"


def _representative_observations(result: PipelineResult, *, maximum: int) -> list[Observation]:
    groups: dict[str, list[Observation]] = defaultdict(list)
    for item in result.observations:
        if item.value is not None and item.evidence:
            groups[metric_key(item)].append(item)
    preferred = [metric.casefold().strip() for metric in result.profile.metrics if metric.strip()]
    ordered = sorted(
        groups.values(),
        key=lambda items: (
            any(name in metric_key(items[0]) for name in preferred),
            len({item.period for item in items if item.period}),
            max(item.confidence for item in items),
        ),
        reverse=True,
    )
    output: list[Observation] = []
    for items in ordered:
        distinct: dict[tuple[object, ...], Observation] = {}
        for item in sorted(items, key=lambda value: (period_sort_key(value.period), -value.confidence)):
            key = (item.period, item.raw_value, item.unit, item.currency)
            distinct.setdefault(key, item)
        output.extend(list(distinct.values())[:3])
        if len(output) >= maximum:
            break
    return output[:maximum]


def _cell_style(cell: Any, *, fill: str, color: str, bold: bool, size: float) -> None:
    from pptx.util import Inches, Pt

    cell.fill.solid()
    cell.fill.fore_color.rgb = _rgb(fill)
    cell.margin_left = cell.margin_right = Inches(0.08)
    cell.margin_top = cell.margin_bottom = Inches(0.04)
    for paragraph in cell.text_frame.paragraphs:
        paragraph.font.name = FONT
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = _rgb(color)


def _number_slides(presentation: Any) -> None:
    for index, slide in enumerate(presentation.slides, start=1):
        if index == 1:
            continue
        _text(slide, str(index), 12.35, 7.08, 0.35, 0.2, size=9, color=MUTED, align="right")


def _page_ranges(result: PipelineResult) -> str:
    ranges = result.profile.analysis_page_ranges
    return ", ".join(f"{start}-{end}" for start, end in ranges) if ranges else f"1-{result.document.page_count}"


def _summary_text(value: str, maximum: int) -> str:
    clean = " ".join(value.replace("—", "-").replace("–", "-").split())
    if len(clean) <= maximum:
        return clean
    clipped = clean[:maximum].rsplit(" ", 1)[0].rstrip(" ,:;-")
    sentence = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
    return clipped[: sentence + 1] if sentence >= maximum // 2 else clipped


def _presentation_chart_title(value: str, observations: list[Observation]) -> str:
    title = value.replace(" — Reported Values", "").replace(" - Reported Values", "").strip()
    labels = list(dict.fromkeys(metric_label(item) for item in observations))
    if len(labels) == 1:
        source_label = labels[0]
        canonical_names = {(item.metric_canonical or "").casefold() for item in observations}
        if any(name and name in title.casefold() for name in canonical_names) and source_label.casefold() not in title.casefold():
            title = source_label
    if " — " in title and len(title) > 72:
        title = title.split(" — ", 1)[1]
    return _summary_text(title, 78)


def _change_summary(observations: list[Observation], scale: float) -> tuple[str, str] | None:
    series_names = {metric_key(item) for item in observations}
    if len(series_names) != 1:
        return None
    by_period: dict[str, Observation] = {}
    for item in observations:
        if item.period and item.value is not None:
            current = by_period.get(item.period)
            if current is None or item.confidence > current.confidence:
                by_period[item.period] = item
    ordered = sorted(by_period.values(), key=lambda item: period_sort_key(item.period))
    if len(ordered) < 2:
        return None
    first, last = ordered[0], ordered[-1]
    start, end = float(first.value or 0), float(last.value or 0)
    if start < 0 <= end:
        headline = "Turned positive"
    elif start > 0 >= end:
        headline = "Turned negative"
    elif first.unit == "percent" or last.unit == "percent":
        headline = f"{end - start:+.1f} pp"
    elif start:
        headline = f"{(end / start - 1) * 100:+.1f}%"
    else:
        headline = f"{(end - start) / scale:+,.1f}"
    detail = f"{_format_scaled(start, scale)} in {first.period} to {_format_scaled(end, scale)} in {last.period}"
    return headline, detail


def _format_scaled(value: float, scale: float) -> str:
    scaled = value / scale
    if abs(scaled) >= 100:
        return f"{scaled:,.0f}"
    if abs(scaled) >= 10:
        return f"{scaled:,.1f}"
    return f"{scaled:,.2f}"


def _usable_charts(result: PipelineResult) -> list[ChartPlan]:
    index = DocumentIndex(result.observations)
    output: list[ChartPlan] = []
    for plan in result.charts:
        observations = [index.get(identifier) for identifier in plan.observation_ids]
        contexts = {
            (item.period, item.entity, tuple(sorted(item.dimensions.items())))
            for item in observations
            if item and item.value is not None
        }
        numeric = [float(item.value) for item in observations if item and item.value is not None]
        # A constant time series communicates no movement and often reflects a
        # tautological percentage row. Keep category comparisons, but avoid
        # spending a presentation slide on a flat period chart.
        has_periods = len({item.period for item in observations if item and item.period}) >= 2
        has_movement = len({round(value, 12) for value in numeric}) >= 2
        if len(contexts) >= 2 and (not has_periods or has_movement):
            output.append(plan)
    return output
