"""Readable opening slides, with source-supported profile pagination.

Semantic priority comes from discovery/insights. These helpers only enforce
readable capacity and remove exact repetitions; they never rewrite a claim.
"""

from dataclasses import dataclass, field
import re
from typing import Any

BODY_PT = 16
HEADING_PT = 18
LINE_HEIGHT_FACTOR = 1.25


@dataclass(frozen=True)
class BriefItem:
    title: str
    text: str
    pages: list[int] = field(default_factory=list)
    short_title: str = ""


def is_technical_copy(text: str) -> bool:
    """Mechanical diagnostics that belong in the data export, not a takeaway."""
    return bool(re.search(
        r"\b(?:slope|intercept|start_value|end_value|turning_points?|r_squared|"
        r"residuals|debug|parser)\b|\b(?:supplied|calculated)\s+(?:\w+\s+){0,3}"
        r"(?:calculation|result)\b|\d+\.\d{6,}|[{}]", text, re.I))


def _copy_height(text: str, width: float, size: int) -> float:
    from .slide_compositor import _lines
    return len(_lines(text, width, size)) * size * LINE_HEIGHT_FACTOR / 72


def _heading_height(text: str, width: float) -> float:
    return _copy_height(text, width, HEADING_PT) + .04 if text else 0


def fits_brief(item: BriefItem, width: float, row_height: float, *, size: int = BODY_PT) -> bool:
    from .slide_compositor import _lines
    heading_lines = len(_lines("00  " + item.title, width, HEADING_PT)) if item.title else 0
    heading_h = _heading_height("00  " + item.title, width) if item.title else 0
    return heading_lines <= 2 and (
        _copy_height(item.text if item.title else "00  " + item.text, width, size)
        <= row_height - heading_h - .18)


def _item_height(item: BriefItem, width: float) -> float:
    text = item.text if item.title else "00  " + item.text
    heading_h = _heading_height("00  " + item.title, width) if item.title else 0
    return heading_h + _copy_height(text, width, BODY_PT) + .18


def overview_items(profile: Any) -> tuple[list[BriefItem], str]:
    """Prefer model-written short points; old profiles use a labelled excerpt."""
    notes = profile.document_summary
    if profile.important_sections:
        notes += "\n\nSource section inventory\n" + "\n".join(profile.important_sections)
    points = list(dict.fromkeys(p.strip() for p in profile.overview_points if p.strip()))
    if points:
        return [BriefItem("", p, profile.document_summary_pages) for p in points], notes
    # Backwards compatible, verbatim whole sentences; never cut a caveat out of
    # a selected sentence. The visible label explicitly identifies an excerpt.
    sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", profile.document_summary.strip())
    items = [BriefItem("", s, profile.document_summary_pages) for s in dict.fromkeys(sentences) if s]
    return items, notes


def render_brief(presentation: Any, title: str, items: list[BriefItem], *,
                 notes: str = "", excerpt: bool = False, max_items: int = 3,
                 row_height_limit: float = 2.8) -> Any:
    """One flat page with bounded complete findings, no shrinking or overflow."""
    from .slide_compositor import _base
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE

    slide, top = _base(presentation, title, "")
    bottom = presentation.slide_height.inches - 1.28
    left, width = .65, presentation.slide_width.inches - 1.3
    selected, seen = [], set()
    used_height = 0.0
    for item in items:
        key = " ".join((item.title + " " + item.text).casefold().split())
        needed = _item_height(item, width)
        if (not item.text.strip() or key in seen or is_technical_copy(item.text)
                or not fits_brief(item, width, min(row_height_limit, bottom - top))
                or used_height + needed + .12 * len(selected) > bottom - top):
            continue
        seen.add(key)
        selected.append(item)
        used_height += needed
        if len(selected) == max_items:
            break
    gap = min(.42, max(0, (bottom - top - used_height) / max(len(selected), 1)))
    y = top
    for i, item in enumerate(selected):
        row_h = _item_height(item, width)
        heading_h = _heading_height("00  " + item.title, width) if item.title else 0
        if item.title:
            heading = _text(slide, f"{i + 1:02d}  {item.title}", left, y, width, heading_h,
                            size=HEADING_PT, bold=True, color=FOURIER_PURPLE)
            heading.name = "brief:heading"
        text = item.text if item.title else f"{i + 1:02d}  {item.text}"
        body = _text(slide, text, left, y + heading_h, width, row_h - heading_h - .16,
                     size=BODY_PT, color=FOURIER_DARK)
        body.name = "brief:body"
        y += row_h + gap
    if not selected:
        _text(slide, "See the evidence pages for supported findings and scope.",
              .75, top, presentation.slide_width.inches - 1.5, 1, size=BODY_PT, color=FOURIER_MUTED)
    if excerpt or len(selected) < len(items):
        _text(slide, "Selected points; full context in speaker notes.", .55, bottom + .08,
              presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    pages = sorted({p for item in selected for p in item.pages})
    _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
          presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    full_copy = "\n\n".join(f"{item.title}\n{item.text}\n{_source_footer(item.pages)}" for item in items)
    slide.notes_slide.notes_text_frame.text = "\n\n".join(s for s in (notes, full_copy) if s)
    return slide


def render_profile(presentation: Any, title: str, items: list[BriefItem], *, notes: str = "") -> list:
    """Paginate supported profile facts instead of silently hiding them in notes."""
    compact_items = [item for item in items if item.text.strip() and not is_technical_copy(item.text)]
    if 3 <= len(compact_items) <= 4:
        compact_page = _render_profile_grid(presentation, title, compact_items, notes)
        if compact_page is not None:
            return [compact_page]
    width = presentation.slide_width.inches - 1.3
    from .slide_compositor import _lines
    # Reserve the template's 32-point continuation title on every page. Header
    # width excludes the original right-hand logo; body copy uses the full width.
    header_width = min(9.06, presentation.slide_width.inches - .60) - .15
    header_lines = len(_lines(title + " (continued)", header_width, 32))
    top = max(1.45, .27 + header_lines * (32 / 72 * 1.22) + .15 + .12)
    capacity = presentation.slide_height.inches - 1.28 - top
    expanded = []
    for item in items:
        if not item.text.strip() or is_technical_copy(item.text):
            continue
        expanded.extend(_split_profile_item(item, width, capacity))
    pages, group, used = [], [], 0.0
    for item in expanded:
        needed = _item_height(item, width)
        if group and used + needed + .12 * len(group) > capacity:
            pages.append(render_brief(presentation, title + (" (continued)" if pages else ""),
                                      group, notes=notes, max_items=len(group), row_height_limit=capacity))
            group, used = [], 0.0
        group.append(item)
        used += needed
    if group:
        pages.append(render_brief(presentation, title + (" (continued)" if pages else ""),
                                  group, notes=notes, max_items=len(group), row_height_limit=capacity))
    return pages or [render_brief(presentation, title, [], notes=notes)]


def _split_profile_item(item: BriefItem, width: float, capacity: float) -> list[BriefItem]:
    """Split oversized copy at a readable page boundary without losing text."""
    remaining = item.text
    parts = []
    while remaining:
        candidate = BriefItem(item.title, remaining, item.pages, item.short_title)
        if _item_height(candidate, width) <= capacity and fits_brief(candidate, width, capacity):
            parts.append(candidate)
            break
        low, high = 1, len(remaining)
        while low < high:
            middle = (low + high + 1) // 2
            piece = BriefItem(item.title, remaining[:middle], item.pages, item.short_title)
            if _item_height(piece, width) <= capacity and fits_brief(piece, width, capacity):
                low = middle
            else:
                high = middle - 1
        if low < 1 or not fits_brief(BriefItem(item.title, remaining[:low], item.pages), width, capacity):
            raise ValueError("Company profile heading exceeds readable page capacity.")
        # Keep clauses together when a boundary falls near the available space.
        boundary = max((match.end() for match in re.finditer(r"(?<=[.!?。！？])\s+|\s+", remaining[:low])
                        if match.end() >= low * .6), default=low)
        parts.append(BriefItem(item.title, remaining[:boundary], item.pages, item.short_title))
        remaining = remaining[boundary:]
    return parts


def _render_profile_grid(presentation: Any, title: str, items: list[BriefItem], notes: str) -> Any | None:
    """Keep a complete company snapshot on one flat page when columns remain readable."""
    from .slide_compositor import _base, _lines
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE

    columns = 3 if len(items) == 3 else 2
    rows = 1 if len(items) == 3 else 2
    left = .65
    gap_x = .34
    gap_y = .18
    total_width = presentation.slide_width.inches - 1.3
    col_width = (total_width - gap_x * (columns - 1)) / columns
    slide, top = _base(presentation, title, "")
    bottom = presentation.slide_height.inches - 1.20
    row_height = (bottom - top - gap_y * (rows - 1)) / rows
    layouts = []
    for item in items:
        heading_lines = len(_lines(item.title, col_width, HEADING_PT))
        heading_h = _heading_height(item.title, col_width)
        body_h = _copy_height(item.text, col_width, BODY_PT) + .08
        if heading_lines > 2 or heading_h + .06 + body_h > row_height:
            slide_id = presentation.slides._sldIdLst[-1]
            presentation.part.drop_rel(slide_id.rId)
            presentation.slides._sldIdLst.remove(slide_id)
            return None
        layouts.append((item, heading_h, body_h))

    for index, (item, heading_h, body_h) in enumerate(layouts):
        column = index % columns
        row = index // columns
        x = left + column * (col_width + gap_x)
        y = top + row * (row_height + gap_y)
        heading = _text(slide, item.title, x, y, col_width, heading_h,
                        size=HEADING_PT, bold=True, color=FOURIER_PURPLE)
        heading.name = "brief:heading"
        body = _text(slide, item.text, x, y + heading_h + .06, col_width,
                     body_h, size=BODY_PT, color=FOURIER_DARK)
        body.name = "brief:body"

    pages = sorted({page for item in items for page in item.pages})
    _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
          presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    full_copy = "\n\n".join(f"{item.title}\n{item.text}\n{_source_footer(item.pages)}" for item in items)
    slide.notes_slide.notes_text_frame.text = "\n\n".join(s for s in (notes, full_copy) if s)
    return slide


def render_summary(presentation: Any, title: str, items: list[BriefItem], *, notes: str = "") -> Any:
    """Four priority findings in two flat columns, keeping complete qualifiers.

    Three or fewer findings keep the full-width opening-slide composition.
    The model's order is preserved; no metric-specific priority rules are applied.
    """
    if len(items) <= 3:
        return render_brief(presentation, title, items, notes=notes)
    from .slide_compositor import _base
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE
    slide, top = _base(presentation, title, "")
    bottom = presentation.slide_height.inches - 1.02
    width = (presentation.slide_width.inches - 1.6) / 2
    row_height = (bottom - top - .10) / 2
    shown = []
    layouts = []
    for item in items[:4]:
        heading_text = item.title
        heading_h = _heading_height(heading_text, width)
        body_h = _copy_height(item.text, width, BODY_PT) + .08
        if heading_h + body_h > row_height and item.short_title:
            heading_text = item.short_title
            heading_h = _heading_height(heading_text, width)
        if heading_h + body_h > row_height or is_technical_copy(item.text):
            return _summary_full_width_fallback(presentation, slide, title, items, notes)
        layouts.append((item, heading_text, heading_h, body_h))
    for i, (item, heading_text, heading_h, body_h) in enumerate(layouts):
        x = .65 + (i % 2) * (width + .30)
        y = top + (i // 2) * (row_height + .10)
        heading = _text(slide, heading_text, x, y, width, heading_h, size=HEADING_PT, bold=True, color=FOURIER_PURPLE)
        heading.name = "brief:heading"
        body = _text(slide, item.text, x, y + heading_h, width, body_h, size=BODY_PT, color=FOURIER_DARK)
        body.name = "brief:body"
        shown.append(item)
    pages = sorted({p for item in shown for p in item.pages})
    _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
          presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    if len(shown) < len(items):
        _text(slide, "Selected points; full context in speaker notes.", .55, bottom,
              presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    full = "\n\n".join(f"{i.title}\n{i.text}\n{_source_footer(i.pages)}" for i in items)
    slide.notes_slide.notes_text_frame.text = notes + "\n\n" + full
    return slide


def _summary_full_width_fallback(presentation, empty_slide, title, items, notes):
    """Drop only the empty local draft before choosing a wider composition."""
    slide_id = presentation.slides._sldIdLst[-1]
    assert presentation.slides[-1] == empty_slide
    presentation.part.drop_rel(slide_id.rId)
    presentation.slides._sldIdLst.remove(slide_id)
    return render_brief(presentation, title, items, notes=notes, max_items=4)
