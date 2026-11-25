"""Measure whole, editable comparison rows against the actual slide headers."""

from dataclasses import dataclass

from .text_capacity import wrap_copy


@dataclass(frozen=True)
class TableGeometry:
    widths: tuple[float, ...]
    header_height: float
    row_heights: tuple[float, ...]


def table_geometries(headers, rows, width):
    """Retain the same readable cell font and column widths on every continuation."""
    count = len(headers)
    fractions = dict.fromkeys((1 / count, .4, .45, .5, .55, .6))
    choices = []
    for fraction in fractions:
        widths = (width * fraction,) + (width * (1 - fraction) / (count - 1),) * (count - 1)
        heights = []
        for row in (headers, *rows):
            lines = max(len(wrap_copy(cell, w - .18, 14)) for cell, w in zip(row, widths))
            heights.append(max(.45, lines * 17 / 72 + .12))
        choices.append(TableGeometry(widths, heights[0], tuple(heights[1:])))
    return tuple(choices)


def page_tops(slide, usual_top, fit_page_budget):
    """Reclaim the empty subtitle band only beneath a measured, visible title."""
    if not fit_page_budget:
        return (usual_top,)
    placeholders = [shape for shape in slide.placeholders if shape.has_text_frame and shape.text.strip()]
    tight_top = min(usual_top, max((p.top.inches + p.height.inches for p in placeholders),
                                   default=usual_top) + .10)
    return usual_top, tight_top


def _page_ends(heights, first_capacity, continuation_capacity):
    ends = []
    start = 0
    while start < len(heights):
        capacity = continuation_capacity if ends else first_capacity
        end = start
        while end < len(heights) and heights[end] <= capacity:
            capacity -= heights[end]
            end += 1
        if end == start:
            return ()
        ends.append(end)
        start = end
    return tuple(ends)


def comparison_layout(geometries, body_heights, first_tops, continuation_tops, bottom):
    """Select by physical page count, then body type size and ordinary title spacing."""
    best = None
    chosen = None
    for geometry in geometries:
        for size, body_height in body_heights.items():
            for spacing, (first, later) in enumerate(zip(first_tops, continuation_tops)):
                available = bottom - geometry.header_height
                ends = _page_ends(geometry.row_heights, available - first - body_height, available - later)
                if not ends:
                    continue
                rank = (len(ends), -size, spacing, sum(geometry.row_heights),
                        abs(geometry.widths[0] - sum(geometry.widths) / len(geometry.widths)))
                if best is None or rank < best:
                    best = rank
                    chosen = geometry, size, spacing, ends
    if chosen is None:
        raise ValueError('Brief comparison row and qualifications exceed readable page capacity.')
    return chosen
