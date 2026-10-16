"""Measured introduction geometry and exact meaning ownership, never semantic approval."""
from collections import defaultdict

from adaptive_document_agent.services.introduction_audience import required_meanings
from adaptive_document_agent.services.source_quotes import normalize_quote


def selected_meaning_source(review):
    """Reuse the complete selected inventory without deciding which meanings to keep."""
    return {'parts': [dict(id=part_id, required_meanings=values)
                      for part_id, values in required_meanings(review).items()]}


def layout_feedback(draft, pages, review, catalog):
    """Expose the same font, wrapping and title reservations used by the layout check."""
    from adaptive_document_agent.services.compact_summary import (
        _template_dimensions, compact_title_errors, compact_body_capacity, compact_heading_errors,
    )
    from adaptive_document_agent.services.presentation_brief import BriefItem, _item_height
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    from adaptive_document_agent.services.slide_compositor import _lines
    from .summary_authored_coverage import meaning_inventory

    path = _resolve_template_path()
    width, height = _template_dimensions(str(path), path.stat().st_mtime_ns)
    copy_width = width - 1.3
    assignments, shared_quotes, owners = defaultdict(list), defaultdict(list), defaultdict(set)
    groups = []
    for group_index, page in enumerate(draft.pages):
        title_lines = len(_lines(page.title, min(8.91, width - .75), 32))
        top = max(1.45, .27 + title_lines * (32 / 72 * 1.22) + .27)
        rows = []
        for item_index, item in enumerate(page.items):
            item_id = f'g{group_index}_i{item_index}'
            needed = _item_height(BriefItem(item.label, item.text, []), copy_width)
            refs = [ref.model_dump(mode='json') for ref in item.meaning_refs]
            for ref in refs:
                key = ref['part_id'], ref['meaning_index']
                # The literal quote already appears once in this paragraph's
                # meaning_refs and in the exact draft. Relationships only need
                # the stable item ID; avoid copying the same long quote again.
                location = dict(item_id=item_id)
                assignments[key].append(location)
                shared_quotes[normalize_quote(ref['summary_quote'])].append(dict(
                    part_id=key[0], meaning_index=key[1], **location))
            for fid in item.fact_ids:
                if fid in catalog:
                    owners[catalog[fid][0].id].add(item_id)
            rows.append(dict(item_id=item_id, label=item.label, characters=len(item.text),
                words=len(item.text.split()), full_width_height_inches=round(needed, 6),
                heading_lines=len(_lines('00  ' + item.label, copy_width, 18)),
                heading_errors=compact_heading_errors(item.label),
                fact_ids=list(item.fact_ids), meaning_refs=refs))
        groups.append(dict(group_id=f'g{group_index}', title=page.title,
            placement=getattr(page, 'placement', 'body'), title_lines=title_lines,
            title_errors=compact_title_errors(page.title),
            continuation_title_lines=len(_lines(page.title + ' (continued)',
                                                min(9.06, width - .60) - .15, 32)),
            full_width_inches=round(copy_width, 6),
            body_capacity_inches=round(compact_body_capacity(page.title, width, height), 6),
            plain_title_body_capacity_inches=round(height - 1.28 - top, 6), paragraphs=rows))
    inventory = meaning_inventory(selected_meaning_source(review))
    body_count = sum(page.placement == 'body' for page in pages) if pages is not None else None
    occupied = 0.0
    for page in pages or []:
        if page.placement != 'body':
            continue
        top = height - 1.28 - compact_body_capacity(page.title, width, height)
        occupied += top + .12 * max(0, len(page.items) - 1)
        occupied += sum(_item_height(BriefItem(item.label, item.text, []), copy_width)
                        for item in page.items)
    return dict(version='physical-meaning-layout-v1', semantic_approval=False,
        template=dict(width_inches=width, height_inches=height, body_font_pt=16,
            paragraph_heading_font_pt=18, title_font_pt=32, footer_reserve_inches=1.28,
            paragraph_gap_inches=.12, max_items_per_physical_slide=4,
            native_title_width_inches=8.91, max_native_title_lines=3, max_paragraph_heading_lines=2),
        pagination_complete=pages is not None,
        score=dict(body_slides=body_count,
            excess_body_slides=(max(0, body_count - (review.max_intro_slides or body_count))
                                if body_count is not None else None),
            invalid_titles=sum(bool(group['title_errors']) for group in groups),
            invalid_paragraph_headings=sum(bool(row['heading_errors']) for group in groups
                                           for row in group['paragraphs']),
            estimated_body_occupied_inches=round(occupied, 6) if pages is not None else None),
        groups=groups, meaning_inventory=inventory,
        meaning_assignments=[dict(part_id=row['part_id'], meaning_index=row['meaning_index'],
                                 locations=assignments[(row['part_id'], row['meaning_index'])])
                             for row in inventory],
        shared_literal_quotes=[dict(quote=quote, references=refs)
            for quote, refs in shared_quotes.items()
            if len({(ref['part_id'], ref['meaning_index']) for ref in refs}) > 1],
        repeated_source_ownership=[dict(part_id=pid, item_ids=sorted(item_ids))
            for pid, item_ids in sorted(owners.items()) if len(item_ids) > 1],
        source_facts=[dict(id=fid, part_id=part.id) for fid, (part, _, _) in catalog.items()])


def compression_progress(previous, current):
    """Count geometry progress only; shorter text or fewer IDs cannot prove coverage."""
    prior, now = previous['score'], current['score']
    prior_titles, current_titles = prior.get('invalid_titles', 0), now.get('invalid_titles', 0)
    prior_headers = prior_titles + prior.get('invalid_paragraph_headings', 0)
    current_headers = current_titles + now.get('invalid_paragraph_headings', 0)
    improved = current_headers < prior_headers
    if current_headers == prior_headers and now['body_slides'] is not None and prior['body_slides'] is not None:
        improved = (now['body_slides'] < prior['body_slides'] or
            (now['body_slides'] == prior['body_slides'] and
             now['estimated_body_occupied_inches'] < prior['estimated_body_occupied_inches'] - .000001))
    return dict(previous=prior, current=now, improved=improved, semantic_approval=False)


def compression_binding_errors(draft, original, catalog):
    """A geometry rewrite must retain original evidence and literal identity fields."""
    previous = {fid for page in original.pages for item in page.items for fid in item.fact_ids}
    current = [fid for page in draft.pages for item in page.items for fid in item.fact_ids]
    errors = []
    if previous - set(current):
        errors.append('Layout compression removed protected source fact IDs: ' + ', '.join(sorted(previous - set(current))))
    if set(current) - catalog.keys():
        errors.append('Layout compression introduced unknown source fact IDs')
    for page in draft.pages:
        for item in page.items:
            if len(item.fact_ids) != len(set(item.fact_ids)):
                errors.append('Layout compression repeated a source fact ID within a paragraph')
    if draft.model_dump(exclude={'pages'}) != original.model_dump(exclude={'pages'}):
        errors.append('Layout compression changed protected document identity fields')
    return errors
