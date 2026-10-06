"""A source-bound view of current stock, period flow and future commitments."""

from __future__ import annotations

import json

from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period


def horizon_data(block, index, document):
    """Validate the selected temporal roles without combining unlike values."""
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

    items = block.horizon_items
    if len(items) != 3 or {item.kind for item in items} != {"stock", "flow", "future"}:
        raise ValueError("Horizon view needs one current stock, one period flow and one future item.")
    pages = {page.page_number: page.text for page in document.pages}
    normalize = lambda text: " ".join(text.casefold().split())
    selected = set(block.observation_ids)
    linked = []
    for item in items:
        if not set(item.source_pages) <= pages.keys():
            raise ValueError("Horizon item cites a page outside available source text.")
        quote = normalize(item.source_quote)
        if not any(quote in normalize(pages[page]) for page in item.source_pages):
            raise ValueError("Horizon quote is absent from cited source pages.")
        if PresentationPlanValidator._numbers(item.label + " " + item.text) - PresentationPlanValidator._numbers(item.source_quote):
            raise ValueError("Horizon text contains a number unsupported by its source quote.")
        observation = index.get(item.observation_id) if item.observation_id else None
        if item.kind in {"stock", "flow"} and observation is None:
            raise ValueError("Current stock and period flow need exact linked observations.")
        if item.observation_id and (item.observation_id not in selected or observation is None
                                    or observation.value is None or not observation.evidence
                                    or observation.validation_status != "valid"
                                    or not set(item.source_pages).intersection(e.page for e in observation.evidence)):
            raise ValueError("Horizon observation must be valid, selected and cited on the item page.")
        if observation and item.kind == "stock" and observation.period_type not in {"point_in_time", "balance_sheet_date"}:
            raise ValueError("Current stock needs a dated point-in-time observation.")
        if observation and item.kind == "flow" and observation.period_type in {"point_in_time", "balance_sheet_date"}:
            raise ValueError("Period flow cannot use a point-in-time balance.")
        linked.append(observation)
    return tuple(zip(items, linked))


def render_horizon(presentation, slide_plan, block, index, document):
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE
    from .slide_compositor import _base, _lines
    from .presentation_header_overflow import visual_header, append_header_commentary

    entries = horizon_data(block, index, document)
    header = visual_header(slide_plan)
    slide, top = _base(presentation, header.title, header.subtitle)
    slide.name = "evidence_horizon"
    width = presentation.slide_width.inches - 1.1
    gap = .35
    column_width = (width - 2 * gap) / 3
    x0 = .55
    for n, (item, observation) in enumerate(entries):
        x = x0 + n * (column_width + gap)
        heading = {"stock": "At a date", "flow": "During a period", "future": "Future obligation"}[item.kind]
        _text(slide, heading, x, top + .04, column_width, .32,
              size=16, bold=True, color=FOURIER_PURPLE).name = "horizon:kind"
        _text(slide, item.label, x, top + .52, column_width, .62,
              size=18, bold=True, color=FOURIER_DARK).name = "horizon:label"
        y = top + 1.22
        if observation:
            value = observation.raw_value.strip() or str(observation.value)
            unit = observation.raw_unit or observation.unit or ""
            if unit and unit.casefold() not in value.casefold():
                value += ("" if unit == "%" else " ") + unit
            if (observation.currency and observation.currency.casefold() not in value.casefold()
                    and observation.currency.casefold() not in unit.casefold()):
                value = observation.currency + " " + value
            _text(slide, value, x, y, column_width, .46,
                  size=22, bold=True, color=FOURIER_PURPLE).name = "horizon:value"
            _text(slide, format_observation_period(observation), x, y + .52, column_width, .28,
                  size=12, color=FOURIER_MUTED).name = "horizon:period"
            y += .94
        lines = _lines(item.text, column_width, 14)
        if len(lines) > 7 or y + len(lines) * .26 > presentation.slide_height.inches - 1.05:
            raise ValueError("Horizon item exceeds readable slide capacity.")
        _text(slide, item.text, x, y, column_width, len(lines) * .26 + .10,
              size=14, color=FOURIER_DARK).name = "horizon:body"
    pages = sorted({page for item, _ in entries for page in item.source_pages})
    _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
          width, .20, size=9, color=FOURIER_MUTED)
    notes = {
        "horizon_items": [item.model_dump(mode="json") for item, _ in entries],
        "source_observations": [obs.model_dump(mode="json") for _, obs in entries if obs],
    }
    slide.notes_slide.notes_text_frame.text = json.dumps(notes, ensure_ascii=False)
    append_header_commentary(presentation, slide_plan, header, pages, notes)
    return slide
