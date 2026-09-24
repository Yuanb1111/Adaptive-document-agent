"""Flat, readable closing pages using the model's retained findings and watch items."""

from __future__ import annotations

import re

from .presentation_brief import BriefItem, _item_height, _split_profile_item, render_profile


def render_closing(presentation, result, plan):
    from .pptx_export import (
        _sanitize_investor_narrative, _source_footer, _text,
        FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE,
    )
    from .slide_compositor import _base

    normalize = lambda text: re.sub(r"\s+", " ", text).strip().casefold()
    insights = [item for item in result.insights if item.id in plan.insight_ids]
    watch_copy = {normalize(item.watch_item) for item in insights if item.watch_item}
    texts = plan.bullets or [item.narrative for item in insights if item.narrative]
    groups = [[], []]
    seen = set()
    for text in texts:
        key = normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        matches = [item for item in insights if key in {
            normalize(item.implication or ""), normalize(item.watch_item or ""), normalize(item.narrative),
        }]
        pages = sorted({e.page for item in matches for e in item.evidence}) or plan.source_pages
        label = matches[0].metric if len(matches) == 1 and matches[0].metric else ""
        groups[int(key in watch_copy)].append(BriefItem(label, _sanitize_investor_narrative(text), pages))

    notes = "\n\n".join(texts)
    if not all(groups):
        # Older plans may contain only conclusions. Keep their exact content
        # without relabelling every implication as a numbered watch item.
        return render_profile(presentation, plan.title, groups[0] or groups[1], notes=notes)

    width = (presentation.slide_width.inches - 1.65) / 2
    capacity = presentation.slide_height.inches - 3.3
    columns = []
    for items in groups:
        batches, batch, used = [], [], 0.0
        for item in items:
            for part in _split_profile_item(item, width, capacity):
                height = _item_height(part, width)
                if batch and used + height + .25 > capacity:
                    batches.append(batch)
                    batch, used = [], 0.0
                batch.append(part)
                used += height + .25
        if batch:
            batches.append(batch)
        columns.append(batches)

    slides = []
    for page in range(max(map(len, columns))):
        title = plan.title + (" (continued)" if page else "")
        slide, top = _base(presentation, title, "")
        visible_pages = set()
        for column, heading in enumerate(("Conclusions", "Watch items")):
            if page >= len(columns[column]):
                continue
            x = .65 + column * (width + .35)
            _text(slide, heading, x, top, width, .4, size=20, bold=True, color=FOURIER_PURPLE)
            y = top + .62
            for item in columns[column][page]:
                height = _item_height(item, width)
                shape = _text(slide, item.text, x, y, width, height,
                              size=18, color=FOURIER_DARK)
                shape.name = "closing:body"
                y += height + .25
                visible_pages.update(item.pages)
        _text(slide, _source_footer(sorted(visible_pages)), .55,
              presentation.slide_height.inches - .82,
              presentation.slide_width.inches - 1.1, .2, size=9, color=FOURIER_MUTED)
        slide.notes_slide.notes_text_frame.text = notes
        slides.append(slide)
    return slides
