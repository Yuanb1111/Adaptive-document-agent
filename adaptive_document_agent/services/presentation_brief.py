"""Bounded opening slides. Full source copy stays in notes, not continuation pages.

Semantic priority comes from discovery/insights. These helpers only enforce
readable capacity and remove exact repetitions; they never rewrite a claim.
"""

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class BriefItem:
    title: str
    text: str
    pages: list[int] = field(default_factory=list)


def is_technical_copy(text: str) -> bool:
    """Mechanical diagnostics that belong in the data export, not a takeaway."""
    return bool(re.search(
        r"\b(?:slope|intercept|start_value|end_value|turning_points?|r_squared|"
        r"residuals|debug|parser)\b|\b(?:supplied|calculated)\s+(?:\w+\s+){0,3}"
        r"(?:calculation|result)\b|\d+\.\d{6,}|[{}]", text, re.I))


def fits_brief(item: BriefItem, width: float, row_height: float, *, size: int = 18) -> bool:
    from .slide_compositor import _lines
    heading_h = .38 if item.title else 0
    return (not item.title or len(_lines("00  " + item.title, width, 19)) <= 1) and (
        len(_lines(item.text if item.title else "00  " + item.text, width, size)) * size * 1.25 / 72
        <= row_height - heading_h - .16)


def _item_height(item: BriefItem, width: float) -> float:
    from .slide_compositor import _lines
    text = item.text if item.title else "00  " + item.text
    return (.38 if item.title else 0) + len(_lines(text, width, 18)) * 18 * 1.25 / 72 + .18


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
                 notes: str = "", excerpt: bool = False) -> Any:
    """One flat page, up to three complete findings, no shrinking or overflow."""
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
                or not fits_brief(item, width, min(2.8, bottom - top))
                or used_height + needed + .12 * len(selected) > bottom - top):
            continue
        seen.add(key)
        selected.append(item)
        used_height += needed
        if len(selected) == 3:
            break
    gap = min(.42, max(0, (bottom - top - used_height) / max(len(selected), 1)))
    y = top
    for i, item in enumerate(selected):
        row_h = _item_height(item, width)
        heading_h = .38 if item.title else 0
        if item.title:
            heading = _text(slide, f"{i + 1:02d}  {item.title}", left, y, width, heading_h,
                            size=19, bold=True, color=FOURIER_PURPLE)
            heading.name = "brief:heading"
        text = item.text if item.title else f"{i + 1:02d}  {item.text}"
        body = _text(slide, text, left, y + heading_h, width, row_h - heading_h - .16,
                     size=18, color=FOURIER_DARK)
        body.name = "brief:body"
        y += row_h + gap
    if not selected:
        _text(slide, "See the evidence pages for supported findings and scope.",
              .75, top, presentation.slide_width.inches - 1.5, 1, size=20, color=FOURIER_MUTED)
    if excerpt or len(selected) < len(items):
        _text(slide, "Selected points; full context in speaker notes.", .55, bottom + .08,
              presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    pages = sorted({p for item in selected for p in item.pages})
    _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
          presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    full_copy = "\n\n".join(f"{item.title}\n{item.text}\n{_source_footer(item.pages)}" for item in items)
    slide.notes_slide.notes_text_frame.text = "\n\n".join(s for s in (notes, full_copy) if s)
    return slide
