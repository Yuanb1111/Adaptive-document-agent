"""Readable native axes from retained values and explicit source dates."""

from datetime import date

from .presentation_style import readable_axis_bounds


def explicit_date_categories(values, categories):
    """Never infer a calendar date from a fiscal year or an unknown period."""
    from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period

    dates = {}
    for item in values:
        if item.period_type != "balance_sheet_date":
            return None
        try:
            point = date.fromisoformat(item.as_of_date or item.period)
        except (TypeError, ValueError):
            return None
        label = format_observation_period(item)
        if label in dates and dates[label] != point:
            return None
        dates[label] = point
    return [dates[label] for label in categories] if all(label in dates for label in categories) else None


def style_date_axis(chart, dates, width):
    """Space points by calendar time; keep full dates in the chart workbook."""
    from pptx.oxml.xmlchemy import OxmlElement

    axis = chart.category_axis
    axis.tick_labels.number_format = "mmm yyyy"
    axis.tick_labels.number_format_is_linked = False
    # Give endpoint labels breathing room beside the value axis and slide edge.
    # This changes the display window only; the workbook retains exact dates.
    padding = max(1, (max(dates) - min(dates)).days * .06)
    origin = date(1899, 12, 30)
    for tag, value in (("c:min", (min(dates) - origin).days - padding),
                       ("c:max", (max(dates) - origin).days + padding)):
        nodes = axis._element.scaling.xpath(tag)
        element = nodes[0] if nodes else OxmlElement(tag)
        element.set("val", str(value))
        if not nodes:
            axis._element.scaling.append(element)
    months = (max(dates).year - min(dates).year) * 12 + max(dates).month - min(dates).month
    target = max(2, int(width))
    step = next((n for n in (1, 3, 6, 12, 24, 60) if n >= months / target), 120)
    for tag, value in (("c:baseTimeUnit", "days"), ("c:majorUnit", str(step)), ("c:majorTimeUnit", "months")):
        nodes = axis._element.xpath(tag)
        element = nodes[0] if nodes else OxmlElement(tag)
        element.set("val", value)
        if not nodes:
            axis._element.append(element)


def style_value_range(axis, values, *, height=None):
    """Use zero for one-sided data and rounded ticks for every native chart."""
    if not values:
        return
    low, high = min(values), max(values)
    if low >= 0:
        low, high = 0.0, high * 1.20 if high else 1.0
    elif high <= 0:
        low, high = low * 1.30, 0.0
    else:
        low, high = low * 1.45, high * 1.25
    low, high, step = readable_axis_bounds(low, high)
    if height is not None:
        # Chart frames include data labels and category labels. Short panels
        # need fewer ticks, while full-height charts keep the regular scale.
        intervals = max(2, min(5, int(max(.4, height - 1.0) / .28)))
        from math import ceil, floor, log10
        raw = (high - low) / intervals
        order = 10 ** floor(log10(raw))
        step = next(n * order for n in (1, 2, 2.5, 5, 10) if n * order >= raw)
        low, high = floor(low / step) * step, ceil(high / step) * step
    axis.minimum_scale, axis.maximum_scale, axis.major_unit = low, high, step
    # Axis labels describe the rounded scale; point labels retain source precision.
    axis.tick_labels.number_format = "0.##;-0.##;0" if step < 1 else "#,##0;-#,##0;0"
    axis.tick_labels.number_format_is_linked = False
