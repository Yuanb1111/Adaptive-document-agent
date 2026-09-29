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
    from .closing_evidence import closing_evidence
    from adaptive_document_agent.validation.presentation_provenance import insight_inputs

    evidence_tables, records = closing_evidence(result, plan)

    normalize = lambda text: re.sub(r"\s+", " ", text).strip().casefold()
    insights = [item for item in result.insights if item.id in plan.insight_ids]
    watch_copy = {normalize(item.watch_item) for item in insights if item.watch_item}
    texts = plan.bullets or [item.narrative for item in insights if item.narrative]
    groups = [[], []]
    linked_groups = {}
    links = insight_inputs(result)
    available = {o.id for o in records}
    all_copy_linked = True
    seen = set()
    for position, text in enumerate(texts):
        key = normalize(text)
        if not key or key in seen:
            continue
        seen.add(key)
        matches = [item for item in insights if key in {
            normalize(item.implication or ""), normalize(item.watch_item or ""), normalize(item.narrative),
        }]
        pages = sorted({e.page for item in matches for e in item.evidence}) or plan.source_pages
        label = matches[0].metric if len(matches) == 1 and matches[0].metric else ""
        column = int(key in watch_copy)
        item = BriefItem(label, _sanitize_investor_narrative(text), pages)
        groups[column].append(item)
        explicit = plan.bullet_observation_ids[position] if position < len(plan.bullet_observation_ids) else []
        observation_ids = set(explicit) if explicit else {
            oid for insight in matches for oid in links.get(insight.id, [])
        }
        # Only explicit plan/analysis links can bind copy to values. An unmatched
        # bullet is not assigned evidence merely because its source page matches.
        if not observation_ids or not observation_ids <= available:
            all_copy_linked = False
            continue
        identity = tuple(sorted(observation_ids))
        if identity not in linked_groups:
            subtitle = matches[0].title if len(matches) == 1 else "Reported values supporting the conclusions"
            linked_groups[identity] = ([[], []], subtitle)
        linked_groups[identity][0][column].append(item)

    notes = "\n\n".join(texts) + "\n\n" + json.dumps(
        {"observations": [o.model_dump(mode="json") for o in records]}, ensure_ascii=False)
    if all_copy_linked and linked_groups:
        combined = _render_linked_pages(presentation, result, plan, linked_groups, records, notes)
        if combined is not None:
            return combined
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


def _render_linked_pages(presentation, result, plan, groups, records, notes):
    """Keep each linked conclusion beside complete, compatible endpoint tables.

    Distinct units retain separate tables. Different period headers are never
    joined or selected away to make a combined layout fit. If a linked bundle
    is incompatible or too large, the original complete pagination takes over.
    """
    from .closing_evidence import closing_evidence

    start_count = len(presentation.slides)
    slides, shown_ids = [], set()
    bundles = []
    for identity, (copy, subtitle) in groups.items():
        evidence_plan = plan.model_copy(update={"insight_ids": [], "observation_ids": list(identity)})
        tables, _ = closing_evidence(result, evidence_plan)
        if not tables or len({key[0] for key, _ in tables}) != 1:
            break
        bundles.append((identity, copy, subtitle, tables))
    else:
        # Join short linked findings only when their complete table signatures
        # agree. The union of source IDs regenerates one table, so shared rows
        # are shown once and no evidence/copy relationship is inferred.
        batches = []
        for bundle in bundles:
            signature = tuple(key for key, _ in bundle[3])
            if batches and batches[-1][0] == signature:
                batches[-1][1].append(bundle)
            else:
                batches.append((signature, [bundle]))
        for _, batch in batches:
            candidate = batch[0]
            if len(batch) > 1:
                identity = sorted({oid for item in batch for oid in item[0]})
                evidence_plan = plan.model_copy(update={"insight_ids": [], "observation_ids": identity})
                merged_tables, _ = closing_evidence(result, evidence_plan)
                merged_copy = [[item for bundle in batch for item in bundle[1][column]] for column in (0, 1)]
                candidate = (tuple(identity), merged_copy,
                             "Reported values supporting the conclusions", merged_tables)
            identity, copy, subtitle, tables = candidate
            slide = _render_linked_page(presentation, plan.title, subtitle, copy, tables, notes)
            if slide is not None:
                slides.append(slide)
                shown_ids.update(identity)
                continue
            _drop_last_slide(presentation)
            if len(batch) == 1:
                break
            for oid, body, heading, source_tables in batch:
                separate = _render_linked_page(presentation, plan.title, heading, body, source_tables, notes)
                if separate is None:
                    _drop_last_slide(presentation)
                    break
                slides.append(separate)
                shown_ids.update(oid)
            else:
                continue
            break
        else:
            # Explicit additional facts remain visible; all raw records also
            # remain in speaker notes.
            remaining = [o.id for o in records if o.id not in shown_ids]
            evidence_plan = plan.model_copy(update={"insight_ids": [], "observation_ids": remaining})
            tables, _ = closing_evidence(result, evidence_plan)
            return _append_evidence_pages(presentation, slides, tables, notes)

    while len(presentation.slides) > start_count:
        slide_id = presentation.slides._sldIdLst[-1]
        presentation.part.drop_rel(slide_id.rId)
        presentation.slides._sldIdLst.remove(slide_id)
    return None


def _drop_last_slide(presentation):
    slide_id = presentation.slides._sldIdLst[-1]
    presentation.part.drop_rel(slide_id.rId)
    presentation.slides._sldIdLst.remove(slide_id)


def _render_linked_page(presentation, title, subtitle, groups, tables, notes):
    from .closing_evidence import render_evidence_table
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE
    from .slide_compositor import _base
    from .text_capacity import wrap_copy

    slide, top = _base(presentation, title, subtitle)
    full_width = presentation.slide_width.inches - 1.1
    table_width = full_width * .55
    table_y = top
    for table in tables:
        shape = render_evidence_table(slide, table, x=.55, y=table_y, width=table_width)
        # Artifact import renumbers native tables; unique names let rendered QA
        # bind each visible table back to its original editable object.
        shape.name = f"closing:evidence:{shape.shape_id}"
        table_y += shape.height.inches + .28
    right, width = .55 + table_width + .3, full_width - table_width - .3
    y = top
    for heading, items in zip(("Conclusions", "Watch items"), groups):
        if not items:
            continue
        _text(slide, heading, right, y, width, .3, size=17, bold=True, color=FOURIER_PURPLE)
        y += .42
        for item in items:
            height = len(wrap_copy(item.text, width - .10, 16)) * .28 + .10
            _text(slide, item.text, right, y, width, height, size=16, color=FOURIER_DARK).name = "closing:body"
            y += height + .18
    if max(y, table_y - .28) > presentation.slide_height.inches - 1.05:
        return None
    pages = sorted({page for _, rows in tables for _, _, sources in rows for page in sources}
                   | {page for items in groups for item in items for page in item.pages})
    note = " | * Unaudited" if any("*" in period for key, _ in tables for period in key[0]) else ""
    _text(slide, _source_footer(pages) + note, .55, presentation.slide_height.inches - .82,
          full_width, .2, size=9, color=FOURIER_MUTED)
    slide.notes_slide.notes_text_frame.text = notes
    return slide


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
