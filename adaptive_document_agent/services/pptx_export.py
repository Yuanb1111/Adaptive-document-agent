"""Editable, presentation-ready PowerPoint export for analysis results."""

from __future__ import annotations

import io
from collections import defaultdict
from typing import Any, Iterable

from adaptive_document_agent.document_model import DocumentIndex, paired_observations, period_sort_key
from adaptive_document_agent.models import ChartPlan, Observation, PipelineResult


SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5
NAVY = "102A43"
INK = "243B53"
MUTED = "627D98"
TEAL = "169C8C"
AMBER = "F4B942"
PALE = "EAF2F8"
WHITE = "FFFFFF"
LIGHT = "F7F9FC"
RED = "C84B31"
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
    for plan in usable_charts[:8]:
        _add_chart_slide(presentation, plan, index)
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
    _background(slide, NAVY)
    accent = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.18), Inches(SLIDE_HEIGHT))
    _solid_shape(accent, TEAL)
    title = result.report_plan.title or "Adaptive Document Analysis"
    _text(slide, title, 0.8, 1.45, 11.3, 1.45, size=34, color=WHITE, bold=True, font=TITLE_FONT)
    _text(slide, result.profile.document_type, 0.82, 3.05, 8.8, 0.45, size=18, color="BFD7EA", bold=True)
    purpose = _truncate(result.profile.document_purpose, 260)
    _text(slide, purpose, 0.82, 3.62, 10.9, 1.25, size=17, color=WHITE)
    ranges = _page_ranges(result)
    _text(slide, f"Analysis scope: {ranges}", 0.82, 6.35, 5.8, 0.35, size=12, color="BFD7EA")
    _text(slide, "Evidence-grounded presentation", 8.2, 6.35, 4.25, 0.35, size=12, color="BFD7EA", align="right")


def _add_evidence_overview(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Evidence overview", "What the analysis retained and validated")
    metrics = {
        (item.metric_canonical or item.metric_original).casefold()
        for item in result.observations
        if (item.metric_canonical or item.metric_original).casefold() not in {"page", "pages"}
    }
    source_pages = {source.page for item in result.observations for source in item.evidence}
    values = [
        (str(len(result.observations)), "retained facts"),
        (str(len(metrics)), "distinct metrics"),
        (str(len(result.charts)), "validated charts"),
        (str(len(source_pages)), "evidence pages"),
    ]
    for index, (value, label) in enumerate(values):
        left = 0.75 + index * 3.08
        _text(slide, value, left, 1.75, 2.45, 0.8, size=34, color=TEAL, bold=True, font=TITLE_FONT)
        _text(slide, label, left, 2.52, 2.45, 0.4, size=15, color=MUTED)
        if index < len(values) - 1:
            _rule(slide, left + 2.55, 1.75, 0.02, 1.2, PALE)
    _text(slide, "Document purpose", 0.75, 3.55, 3.0, 0.4, size=17, color=INK, bold=True)
    _text(slide, _truncate(result.profile.document_purpose, 420), 0.75, 4.05, 11.7, 1.15, size=17, color=INK)
    focus = _truncate(result.profile.analysis_focus or "Automatic discovery", 280)
    _text(slide, "Analysis focus", 0.75, 5.55, 2.2, 0.35, size=15, color=MUTED, bold=True)
    _text(slide, focus, 2.35, 5.5, 10.0, 0.7, size=16, color=INK)


def _add_chart_slide(presentation: Any, plan: ChartPlan, index: DocumentIndex) -> None:
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_DATA_LABEL_POSITION, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    slide = _base_slide(presentation, _presentation_chart_title(plan.title), _truncate(plan.question, 150))
    observations = [index.get(identifier) for identifier in plan.observation_ids]
    values = [item for item in observations if item and item.value is not None]
    if not values:
        _text(slide, "The chart plan contains no usable values.", 0.85, 2.4, 11.4, 0.8, size=22, color=MUTED, align="center")
        return

    max_abs = max(abs(float(item.value or 0)) for item in values)
    scale, scale_label = _display_scale(values, max_abs)
    chart_left, chart_top, chart_width, chart_height = Inches(0.78), Inches(1.65), Inches(11.82), Inches(4.65)

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
        color = (TEAL, NAVY, AMBER, RED)[series_index % 4]
        try:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = _rgb(color)
            series.format.line.color.rgb = _rgb(color)
        except (AttributeError, ValueError):
            pass
    try:
        chart.plots[0].has_data_labels = True
        labels = chart.plots[0].data_labels
        labels.position = XL_DATA_LABEL_POSITION.OUTSIDE_END if plan.chart_type not in {"line", "area", "pie"} else XL_DATA_LABEL_POSITION.ABOVE
        labels.font.name = FONT
        labels.font.size = Pt(10)
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
    _text(slide, unit, 0.82, 6.35, 5.4, 0.35, size=11, color=MUTED)
    pages = ", ".join(map(str, plan.source_pages)) or "not available"
    _text(slide, f"Source pages: {pages}", 7.0, 6.35, 5.55, 0.35, size=11, color=MUTED, align="right")


def _add_no_chart_slide(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Chart availability", "Why no visual passed the evidence checks")
    _text(slide, "No chart met the current usefulness and evidence thresholds.", 0.9, 2.0, 11.4, 0.8, size=26, color=INK, bold=True, align="center")
    _text(
        slide,
        "The presentation preserves this outcome instead of drawing unsupported comparisons. Review the extracted periods, units and validation warnings before using the data for decisions.",
        1.45,
        3.15,
        10.4,
        1.35,
        size=19,
        color=MUTED,
        align="center",
    )
    _text(slide, f"Retained observations: {len(result.observations)}", 4.15, 5.2, 5.0, 0.45, size=17, color=TEAL, bold=True, align="center")


def _add_findings_slide(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Key findings", "Evidence-backed conclusions from the analysis")
    findings = sorted(result.insights, key=lambda item: (item.importance, item.confidence), reverse=True)[:5]
    if not findings:
        _text(slide, "No validated analytical findings were produced.", 0.9, 2.4, 11.4, 0.8, size=22, color=MUTED, align="center")
        return
    top = 1.55
    for number, finding in enumerate(findings, start=1):
        _text(slide, f"{number:02d}", 0.78, top + 0.04, 0.52, 0.35, size=14, color=TEAL, bold=True)
        _text(slide, _truncate(finding.title, 90), 1.38, top, 4.1, 0.43, size=17, color=INK, bold=True)
        pages = sorted({source.page for source in finding.evidence})
        source = f"Pages {', '.join(map(str, pages))}" if pages else "Calculated from retained evidence"
        _text(slide, _truncate(finding.narrative, 250), 5.5, top, 5.85, 0.77, size=15, color=INK)
        _text(slide, source, 11.35, top + 0.03, 1.15, 0.55, size=9, color=MUTED, align="right")
        _rule(slide, 1.38, top + 0.86, 11.1, 0.012, PALE)
        top += 1.0


def _add_quality_slide(presentation: Any, result: PipelineResult) -> None:
    slide = _base_slide(presentation, "Data quality and limitations", "Items that affect interpretation")
    messages = list(dict.fromkeys([
        *result.profile.data_quality_notes,
        *(warning.message for warning in result.validation_warnings if warning.severity in {"error", "warning"}),
    ]))[:7]
    if not messages:
        messages = ["No material data-quality warning was retained for this analysis."]
    top = 1.55
    for message in messages:
        _text(slide, "•", 0.85, top, 0.25, 0.35, size=18, color=AMBER, bold=True)
        _text(slide, _truncate(message, 280), 1.18, top, 11.0, 0.62, size=15, color=INK)
        top += 0.74


def _add_evidence_table_slide(presentation: Any, result: PipelineResult) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    slide = _base_slide(presentation, "Evidence appendix", "Selected reported values with page-level provenance")
    observations = _representative_observations(result, maximum=10)
    headers = ["Metric", "Period", "Reported value", "Unit", "Page"]
    rows = [
        [
            _truncate(item.metric_canonical or item.metric_original, 48),
            item.period or "—",
            item.raw_value,
            "percent" if item.unit == "percent" else item.raw_unit or _unit_label([item], ""),
            ", ".join(map(str, sorted({source.page for source in item.evidence}))),
        ]
        for item in observations
    ]
    table_shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(0.72), Inches(1.55), Inches(11.9), Inches(5.15))
    table = table_shape.table
    widths = [4.55, 1.28, 2.05, 2.7, 0.95]
    for column, width in zip(table.columns, widths):
        column.width = Inches(width)
    for column, header in enumerate(headers):
        cell = table.cell(0, column)
        cell.text = header
        _cell_style(cell, fill=NAVY, color=WHITE, bold=True, size=13)
    for row_index, values in enumerate(rows, start=1):
        for column, value in enumerate(values):
            cell = table.cell(row_index, column)
            cell.text = str(value)
            _cell_style(cell, fill=WHITE if row_index % 2 else LIGHT, color=INK, bold=False, size=11)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT if column in {2, 4} else PP_ALIGN.LEFT
    for row in table.rows:
        row.height = Inches(0.45)
    _text(slide, "Values remain traceable to the original PDF pages. See the JSON and CSV exports for the complete retained fact base.", 0.76, 6.78, 11.75, 0.28, size=10, color=MUTED)


def _base_slide(presentation: Any, title: str, subtitle: str = "") -> Any:
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    _background(slide, WHITE)
    _text(slide, title, 0.72, 0.38, 11.7, 0.58, size=27, color=NAVY, bold=True, font=TITLE_FONT)
    if subtitle:
        _text(slide, subtitle, 0.74, 1.0, 11.4, 0.3, size=12, color=MUTED)
    _rule(slide, 0.72, 1.34, 11.9, 0.025, TEAL)
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
        series = item.entity or (item.metric_canonical or item.metric_original)
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
            groups[(item.metric_canonical or item.metric_original).casefold()].append(item)
    preferred = [metric.casefold().strip() for metric in result.profile.metrics if metric.strip()]
    ordered = sorted(
        groups.values(),
        key=lambda items: (
            any(name in (items[0].metric_canonical or items[0].metric_original).casefold() for name in preferred),
            len({item.period for item in items if item.period}),
            max(item.confidence for item in items),
        ),
        reverse=True,
    )
    output: list[Observation] = []
    for items in ordered:
        output.extend(sorted(items, key=lambda item: period_sort_key(item.period))[:3])
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
    return ", ".join(f"{start}–{end}" for start, end in ranges) if ranges else f"1–{result.document.page_count}"


def _truncate(value: str, maximum: int) -> str:
    clean = " ".join(value.split())
    return clean if len(clean) <= maximum else clean[: maximum - 1].rstrip() + "…"


def _presentation_chart_title(value: str) -> str:
    title = value.replace(" — Reported Values", "").strip()
    if " — " in title and len(title) > 66:
        title = title.split(" — ", 1)[1]
    return _truncate(title, 66)


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
        if len(contexts) >= 2:
            output.append(plan)
    return output
