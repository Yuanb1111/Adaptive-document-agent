"""Flat, readable closing pages using the model's retained findings and watch items."""

from __future__ import annotations

import re
import json

from .presentation_brief import BriefItem, _item_height, _split_profile_item, render_profile


def render_closing(presentation, result, plan):
    from .pptx_export import (
        _sanitize_investor_narrative, _source_footer, _text,
        FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE,
    )
    from .slide_compositor import _base
    from .closing_evidence import closing_evidence, render_evidence_table

    evidence_tables, records = closing_evidence(result, plan)

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

    notes = "\n\n".join(texts) + "\n\n" + json.dumps(
        {"observations": [o.model_dump(mode="json") for o in records]}, ensure_ascii=False)
    # A compact endpoint table makes the linked facts visible beside the
    # interpretation. Different period/unit groups get separate evidence pages.
    if all(groups) and len(evidence_tables) == 1 and len(evidence_tables[0][1]) <= 6:
        from .text_capacity import wrap_copy
        slide, top = _base(presentation, plan.title, "First and latest reported values supporting the conclusions")
        full_width = presentation.slide_width.inches - 1.1
        table_width = full_width * .55
        table = render_evidence_table(slide, evidence_tables[0], x=.55, y=top, width=table_width)
        right, width = .55 + table_width + .3, full_width - table_width - .3
        y = top
        for heading, items in zip(("Conclusions", "Watch items"), groups):
            _text(slide, heading, right, y, width, .3, size=17, bold=True, color=FOURIER_PURPLE)
            y += .42
            for item in items:
                height = len(wrap_copy(item.text, width - .10, 16)) * .27 + .10
                _text(slide, item.text, right, y, width, height, size=16, color=FOURIER_DARK)
                y += height + .18
        bottom = presentation.slide_height.inches - 1.05
        if max(y, table.top.inches + table.height.inches) <= bottom:
            pages = sorted({e.page for o in records for e in o.evidence})
            note = " | * Unaudited" if any("*" in period for period in evidence_tables[0][0][0]) else ""
            _text(slide, _source_footer(pages) + note, .55, presentation.slide_height.inches - .82,
                  full_width, .2, size=9, color=FOURIER_MUTED)
            slide.notes_slide.notes_text_frame.text = notes
            return [slide]
        # Reflow through the original pagination if combined content is too tall.
        slide_id = presentation.slides._sldIdLst[-1]
        presentation.part.drop_rel(slide_id.rId)
        presentation.slides._sldIdLst.remove(slide_id)
    if not all(groups):
        # Older plans may contain only conclusions. Keep their exact content
        # without relabelling every implication as a numbered watch item.
        slides = render_profile(presentation, plan.title, groups[0] or groups[1], notes=notes)
        return _append_evidence_pages(presentation, slides, evidence_tables, notes)

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
    return _append_evidence_pages(presentation, slides, evidence_tables, notes)


def _append_evidence_pages(presentation, slides, tables, notes):
    from .closing_evidence import render_evidence_table
    from .slide_compositor import _base
    from .pptx_export import _text, _source_footer, FOURIER_MUTED
    evidence_slides = []
    for key, rows in tables:
        for start in range(0, len(rows), 6):
            shown = rows[start:start + 6]
            slide, top = _base(presentation, "Evidence supporting the conclusions", "Reported values with source references")
            render_evidence_table(slide, (key, shown), x=.55, y=top, width=presentation.slide_width.inches - 1.1).name = "evidence:packable"
            pages = sorted({page for _, _, source_pages in shown for page in source_pages})
            note = " | * Unaudited" if any("*" in period for period in key[0]) else ""
            _text(slide, _source_footer(pages) + note, .55, presentation.slide_height.inches - .82,
                  presentation.slide_width.inches - 1.1, .2, size=9, color=FOURIER_MUTED).name = "evidence:footer"
            slide.notes_slide.notes_text_frame.text = notes
            evidence_slides.append(slide)
    from .evidence_page_packing import pack_evidence_pages
    slides.extend(pack_evidence_pages(presentation, evidence_slides))
    return slides
