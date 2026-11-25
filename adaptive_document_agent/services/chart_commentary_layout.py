"""Flow source-qualified chart commentary beside and below a native plot."""
from .slide_compositor import CompositionGeometry, Rect, _ChartCapacityError
from .presentation_style import GUTTER


def chart_copy_geometry(geometry, top, chart_minimum, bottom):
    """Keep the chart readable while giving long text two sequential reading zones."""
    footer = geometry.footer
    min_width, min_height, categories = chart_minimum
    if categories:
        raise _ChartCapacityError('Keep the original legend and space for a composition chart.')
    chart_width = max(min_width, footer.w * .46)
    # Allow a panel title, unit, annotation and the independent minimum plot height.
    panel_height = min_height + 1.04
    side_width = footer.w - chart_width - GUTTER
    lower_top = top + panel_height + GUTTER
    if side_width < 3 or bottom - top < panel_height:
        raise _ChartCapacityError('Insufficient space beside the chart.')
    band = None
    if bottom - lower_top >= .65:
        band = Rect(footer.x, lower_top, footer.w, bottom - lower_top)
    else:
        panel_height = bottom - top
    chart = Rect(footer.x, top, chart_width, panel_height)
    side = Rect(footer.x + chart_width + GUTTER, top, side_width, panel_height)
    return CompositionGeometry([chart], None, side, footer), band


def fit_bounded_chart_copy(presentation, rendered, plan, charts, result, index, preserve_charts):
    """Choose the alternate layout only when it saves a whole physical page."""
    from .slide_budgets import report_budget
    if (len(rendered) < 2 or len(charts) != 1 or report_budget(result) is None
            or any(shape.has_table for page in rendered for shape in page.shapes)
            or not any(shape.has_chart for shape in rendered[0].shapes)):
        return rendered
    from .composition_pagination import _remove_pages
    from .qa_reporter import CriticalQAError
    from .slide_compositor import _render_composed_slide, validate_composed_geometry

    start = len(presentation.slides)
    try:
        candidate = _render_composed_slide(presentation, plan, charts, result, index,
            preserve_charts=preserve_charts, compact_narrative=True)
        if len(candidate) < len(rendered):
            before = [(s.name, s.text) for s in rendered[0].shapes if s.name.startswith('annotation:')]
            after = [(s.name, s.text) for s in candidate[0].shapes if s.name.startswith('annotation:')]
            if before == after:
                validate_composed_geometry(presentation)
                _remove_pages(presentation, rendered)
                return candidate
    except (_ChartCapacityError, CriticalQAError):
        pass
    _remove_pages(presentation, list(presentation.slides)[start:])
    return rendered
