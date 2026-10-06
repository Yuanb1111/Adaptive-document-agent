"""Preserve planned copy when evidence visuals need a shorter header."""

from dataclasses import dataclass
import json

from adaptive_document_agent.models import PresentationSlide

from .slide_compositor import Rect, _base, _lines, _put_commentary, _put_text, _split_header_subtitle
from .presentation_style import FOOTNOTE_PT, MUTED


@dataclass(frozen=True)
class VisualHeader:
    title: str
    subtitle: str
    overflow: str


def visual_header(plan: PresentationSlide) -> VisualHeader:
    """Move excess copy to body text, without rewriting the analytical claim."""
    title = plan.title
    overflow_title = ""
    if len(_lines(title, 8.91, 32)) > 3:
        title = (plan.section_title if plan.section_title
                 and len(_lines(plan.section_title, 8.91, 32)) <= 2 else "Analysis")
        overflow_title = plan.title
    subtitle, overflow = _split_header_subtitle(plan.message)
    return VisualHeader(title, subtitle, "\n\n".join(
        part for part in (overflow_title, overflow) if part))


def append_header_commentary(presentation, plan: PresentationSlide, header: VisualHeader,
                             source_pages: list[int], evidence_notes: dict) -> None:
    """Append readable, cited pages while keeping the visual renderer's return value."""
    from .pptx_export import _source_footer

    remaining = header.overflow
    if not remaining:
        return
    pages = sorted(set(source_pages) | set(plan.source_pages))
    notes = json.dumps({**evidence_notes, "slide_plan": plan.model_dump(mode="json"),
                        "source_pages": pages}, ensure_ascii=False)
    width = presentation.slide_width.inches - 1.1
    bottom = presentation.slide_height.inches - 1.02
    while remaining:
        slide, top = _base(presentation, header.title, "Continued commentary")
        slide.name = "composed_special_visual_commentary"
        if bottom - top < .75:
            raise ValueError("Presentation header leaves no readable commentary capacity.")
        rest = _put_commentary(slide, remaining, Rect(.55, top, width, bottom - top))
        if len(rest) >= len(remaining):
            raise ValueError("Presentation commentary cannot fit readable text.")
        remaining = rest
        _put_text(slide, _source_footer(pages),
                  Rect(.55, presentation.slide_height.inches - .82, width, .20),
                  size=FOOTNOTE_PT, color=MUTED)
        slide.notes_slide.notes_text_frame.text = notes
