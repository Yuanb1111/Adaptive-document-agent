"""Editable flow of model-selected, source-quoted operating stages."""

from __future__ import annotations

import json


def can_render_value_chain(company, slide_width: float) -> bool:
    from .slide_compositor import _lines
    steps = company.value_chain
    if not 3 <= len(steps) <= 5:
        return False
    right_gap = .24
    total = slide_width - 1.2
    width = (total - right_gap * (len(steps) - 1)) / len(steps)
    # Optional visual: retain the narrative company pages if the flow cannot
    # fit without shrinking source-backed text below a readable size.
    if any(len(_lines(item.label, width - .18, 17)) > 2
           or len(_lines(item.text, width - .18, 14)) > 7 for item in steps):
        return False
    return True


def render_value_chain(presentation, company):
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE
    from .slide_compositor import _base, _lines

    if not can_render_value_chain(company, presentation.slide_width.inches):
        return None
    steps = company.value_chain
    left, right_gap = .60, .24
    total = presentation.slide_width.inches - 1.2
    width = (total - right_gap * (len(steps) - 1)) / len(steps)
    slide, top = _base(presentation, "How the business operates", "Source-supported operating sequence")
    slide.name = "company_value_chain"
    for n, item in enumerate(steps):
        x = left + n * (width + right_gap)
        _text(slide, f"{n + 1:02d}", x, top + .02, width, .34,
              size=18, bold=True, color=FOURIER_PURPLE).name = "value_chain:number"
        heading_lines = len(_lines(item.label, width - .18, 17))
        heading_h = max(.30, heading_lines * .29)
        _text(slide, item.label, x, top + .52, width - .18, heading_h,
              size=17, bold=True, color=FOURIER_DARK).name = "value_chain:label"
        body_lines = len(_lines(item.text, width - .18, 14))
        _text(slide, item.text, x, top + .65 + heading_h, width - .18,
              body_lines * .25 + .12, size=14, color=FOURIER_DARK).name = "value_chain:body"
        if n < len(steps) - 1:
            _text(slide, "→", x + width + .02, top + .31, right_gap - .04, .25,
                  size=14, color=FOURIER_PURPLE).name = "value_chain:connector"
    pages = sorted({page for item in steps for page in item.source_pages})
    _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
          presentation.slide_width.inches - 1.1, .20, size=9, color=FOURIER_MUTED)
    slide.notes_slide.notes_text_frame.text = json.dumps(
        [item.model_dump(mode="json") for item in steps], ensure_ascii=False, indent=2)
    return slide
