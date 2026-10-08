"""Flat, readable closing pages using the model's retained findings and watch items."""

from __future__ import annotations

import re
import json

from .presentation_brief import BriefItem, _item_height, _split_profile_item, render_profile


def render_closing(presentation, result, plan):
    # The final source-validated briefing supersedes earlier insight drafts.
    # Reuse its model-authored findings so a stale watch question cannot
    # contradict the summary. Comparisons already have dedicated body pages.
    if result.executive_brief is not None:
        from .executive_brief import brief_items
        from .presentation_summary import render_complete_summary
        findings = [item for item in brief_items(result) if item.table is None]
        if findings:
            from adaptive_document_agent.agent.topic_coverage_review import coverage_review_pending
            pending = coverage_review_pending(result)
            notes = json.dumps({'executive_brief': result.executive_brief.model_dump(mode='json'),
                                'superseded_closing_plan': plan.model_dump(mode='json'),
                                'coverage_review_pending': pending}, ensure_ascii=False)
            slides = render_complete_summary(presentation, 'Conclusions', findings, notes=notes)
            if pending:
                from .pptx_export import _text, FOURIER_MUTED
                _text(slides[0], 'Coverage review incomplete. Material omissions may remain; complete review before final use.',
                      .65, 1.05, presentation.slide_width.inches - 1.3, .32,
                      size=12, color=FOURIER_MUTED).name = 'brief:coverage_status'
            return slides
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
        for column, heading in enumerate(("What it means", "What to monitor")):
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
    """Keep each linked conclusion beside complete, compatible reported series.

    Distinct units retain separate tables. Different period headers are never
    joined or selected away to make a combined layout fit. If a linked bundle
    is incompatible or too large, the original complete pagination takes over.
    """
    from .closing_evidence import closing_evidence

    start_count = len(presentation.slides)
    bundles = []
    for identity, (copy, subtitle) in groups.items():
        evidence_plan = plan.model_copy(update={"insight_ids": [], "observation_ids": list(identity)})
        tables, _ = closing_evidence(result, evidence_plan)
        if not tables or len({key[0] for key, _ in tables}) != 1:
            break
        bundles.append((identity, copy, subtitle, tables))
    else:
        # Pack linked findings with matching complete period headers,
        # even when the selected copy interleaves different period groups.
        # First appearance sets page order; the union of source IDs regenerates
        # each table so shared rows are shown once. Different units keep their
        # own labelled tables while participating in the same measured paging.
        batches = {}
        for bundle in bundles:
            signature = tuple(sorted({key[0] for key, _ in bundle[3]}))
            batches.setdefault(signature, []).append(bundle)

        def merge_batch(batch):
            if len(batch) == 1:
                return batch[0]
            identity = sorted({oid for item in batch for oid in item[0]})
            evidence_plan = plan.model_copy(update={"insight_ids": [], "observation_ids": identity})
            merged_tables, _ = closing_evidence(result, evidence_plan)
            merged_copy = [[item for bundle in batch for item in bundle[1][column]] for column in (0, 1)]
            return (tuple(identity), merged_copy,
                    "Reported values supporting the conclusions", merged_tables)

        candidates = [(merge_batch(batch), batch) for batch in batches.values()]
        packed = _render_linked_bundle_pages(presentation, plan.title, candidates, notes,
                                            merge_batch=merge_batch)
        if packed is not None:
            slides, shown_ids = packed
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


def _render_linked_bundle_pages(presentation, title, candidates, notes, *, merge_batch):
    """Pack short linked findings while retaining separate table headers."""
    from .closing_evidence import evidence_table_layout, render_evidence_table
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE
    from .slide_compositor import _base
    from .text_capacity import wrap_copy

    full_width = presentation.slide_width.inches - 1.1
    table_width = full_width * .34
    right, copy_width = .55 + table_width + .30, full_width - table_width - .30
    subtitle = "Reported values supporting the conclusions"
    slide, top = _base(presentation, title, subtitle)
    bottom = presentation.slide_height.inches - 1.05

    def dimensions(bundle):
        _, groups, heading, tables = bundle
        stacked = any(len(key[0]) > 2 for key, _ in tables)
        text_width = full_width if stacked else copy_width
        evidence_width = full_width if stacked else table_width
        watch_only = bool(groups[1]) and not groups[0] and heading != subtitle and not stacked
        topic_height = (len(wrap_copy(heading, text_width if watch_only else full_width, 16)) * .25 + .10
                        if heading != subtitle else 0.0)
        table_height = sum(sum(evidence_table_layout(table, evidence_width)[2]) + .10 for table in tables)
        copy_height = topic_height if watch_only else 0.0
        for column, items in enumerate(groups):
            if not items:
                continue
            if column and groups[0]:
                copy_height += .08
            copy_height += sum(len(wrap_copy(item.text, text_width - .10, 15)) * .245 + .18
                               for item in items)
        if stacked:
            return topic_height + table_height + .14 + copy_height, topic_height, watch_only, stacked
        return (max(table_height, copy_height) if watch_only
                else topic_height + max(table_height, copy_height)), topic_height, watch_only, stacked

    bundles = []
    for candidate, originals in candidates:
        if dimensions(candidate)[0] <= bottom - top:
            bundles.append(candidate)
        elif len(originals) > 1:
            # A whole compatible batch may be too tall although two complete
            # subgroups fit. Minimize pages, then balance measured whitespace;
            # regenerate each subgroup's table from its full original IDs.
            capacity = bottom - top
            best = [(0, 0.0, [])] + [None] * len(originals)
            for end in range(1, len(originals) + 1):
                for start in range(end):
                    if best[start] is None:
                        continue
                    merged = merge_batch(originals[start:end])
                    needed = dimensions(merged)[0]
                    if needed > capacity:
                        continue
                    previous = best[start]
                    option = (previous[0] + 1, previous[1] + (capacity - needed) ** 2,
                              [*previous[2], merged])
                    if best[end] is None or option[:2] < best[end][:2]:
                        best[end] = option
            if best[-1] is None:
                return None
            bundles.extend(best[-1][2])
        else:
            return None

    slides, shown_ids = [], set()
    y, pages, unaudited = top, set(), False

    def finish_page():
        note = " | * Unaudited" if unaudited else ""
        _text(slide, _source_footer(sorted(pages)) + note, .55,
              presentation.slide_height.inches - .82, full_width, .2,
              size=9, color=FOURIER_MUTED)
        slide.notes_slide.notes_text_frame.text = notes
        slides.append(slide)

    for identity, groups, heading, tables in bundles:
        height, topic_height, watch_only, stacked = dimensions((identity, groups, heading, tables))
        if y > top and y + height > bottom:
            finish_page()
            slide, top = _base(presentation, title + " (continued)", subtitle)
            y, pages, unaudited = top, set(), False
        if y + height > bottom:
            return None
        if topic_height and not watch_only:
            _text(slide, heading, .55, y, full_width, topic_height, size=16,
                  bold=True, color=FOURIER_PURPLE)
        row_top = y + (0 if watch_only else topic_height)
        table_y = row_top
        for table in tables:
            shape = render_evidence_table(slide, table, x=.55, y=table_y,
                                          width=full_width if stacked else table_width)
            # Artifact import renumbers native tables; unique names retain
            # one-to-one provenance checks for every editable table.
            shape.name = f"closing:evidence:{shape.shape_id}"
            table_y += shape.height.inches + .10
            pages.update(page for _, _, sources in table[1] for page in sources)
            unaudited |= any("*" in period for period in table[0][0])
        copy_y = table_y + .14 if stacked else row_top
        copy_x, current_copy_width = (.55, full_width) if stacked else (right, copy_width)
        if watch_only:
            _text(slide, heading, right, copy_y, copy_width, topic_height,
                  size=16, bold=True, color=FOURIER_PURPLE)
            copy_y += topic_height
        for column, items in enumerate(groups):
            if not items:
                continue
            if column and groups[0]:
                copy_y += .08
            for item in items:
                body_height = len(wrap_copy(item.text, current_copy_width - .10, 15)) * .245 + .08
                _text(slide, item.text, copy_x, copy_y, current_copy_width, body_height,
                      size=15, color=FOURIER_PURPLE if column else FOURIER_DARK).name = "closing:body"
                copy_y += body_height + .10
                pages.update(item.pages)
        shown_ids.update(identity)
        y += height + .12
    finish_page()
    return slides, shown_ids


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
