"""Measure complete-item transfers; only the model may choose coherent groups."""
import json
from typing import Literal

from pydantic import ConfigDict, Field, create_model

MAX_TRANSFER_PROBES = 48
MAX_TRANSFER_CHOICES = 8


def transferred_draft(draft, source, item, destination):
    revised = draft.model_copy(deep=True)
    value = revised.pages[source].items.pop(item)
    revised.pages[destination].items.append(value)
    return type(draft).model_validate(revised.model_dump(mode='json'))


def allocation_choices(draft, catalog, review, expand):
    """Bounded geometric candidates, never evidence selection or semantic approval.

    Move one complete non-opening paragraph out of an overflowing group into
    another existing body group. Keep every heading, label, word, display hint,
    fact ID and meaning reference. Empty groups and appendices are excluded.
    """
    from .summary_theme_layout import pack_theme_pages, SummaryLayoutError
    if review.max_intro_slides is None:
        return {}
    probe_review = review.model_copy(deep=True)

    def count(page):
        probe = draft.model_copy(update={'pages': [page]})
        return len(pack_theme_pages(expand(probe, catalog, probe_review)))

    try:
        counts = [count(page) for page in draft.pages]
    except (SummaryLayoutError, ValueError):
        return {}
    body = [i for i, page in enumerate(draft.pages) if getattr(page, 'placement', 'body') == 'body']
    total = sum(counts[i] for i in body)
    choices, probes = {}, 0
    for source in body:
        if counts[source] <= 1 or len(draft.pages[source].items) <= 1:
            continue
        for item in range(len(draft.pages[source].items)):
            if source == body[0] and item == 0:
                continue  # Keep the supported opening paragraph in place.
            for destination in body:
                if destination == source:
                    continue
                if probes >= MAX_TRANSFER_PROBES or len(choices) >= MAX_TRANSFER_CHOICES:
                    return choices
                probes += 1
                try:
                    candidate = transferred_draft(draft, source, item, destination)
                    new_source, new_destination = count(candidate.pages[source]), count(candidate.pages[destination])
                except (SummaryLayoutError, ValueError):
                    continue
                pages = total - counts[source] - counts[destination] + new_source + new_destination
                if new_source >= counts[source] or pages > review.max_intro_slides:
                    continue
                choices[f'transfer_{len(choices)}'] = dict(source=source, item=item, destination=destination,
                    original_physical_pages=total, physical_pages=pages,
                    source_item_id=f'g{source}_i{item}', destination_group_id=f'g{destination}')
    return choices


def choose_allocation(gateway, draft, catalog, review, record, choices, schema, *, instruction='', cancelled=None):
    """Spend the existing final repair on an exact transfer or a full rewrite."""
    from concurrent.futures import CancelledError
    from .prompting import untrusted_document_message
    from .summary_layout_patch import layout_patch_schema, layout_patch_messages, apply_layout_patch
    from .summary_writer_copy import writer_schema, bind_writer_copy
    if cancelled is not None and cancelled.is_set():
        raise CancelledError('Summary layout allocation cancelled')
    patch_schema = layout_patch_schema(schema)
    response_schema = create_model('SummaryLayoutAllocation', __config__=ConfigDict(extra='forbid'),
        choice=(Literal[tuple(['keep', *choices])], ...),
        source_title=(str | None, Field(default=None, min_length=1, max_length=65)),
        destination_title=(str | None, Field(default=None, min_length=1, max_length=65)),
        replacement=(patch_schema | None, None))
    audit = record['lossless_layout_allocation'] = dict(menu=choices, status='pending',
        semantic_approval=False, additional_rewrite_round=False)
    messages = layout_patch_messages(draft, catalog, record, instruction,
                                    audience_selected=review.audience_part_ids is not None)
    messages[0]['content'] = messages[0]['content'].replace(
        'Return ONLY pages under the schema;', 'Return the requested allocation choice under the schema;')
    messages[0]['content'] += (
        ' This is the FINAL existing repair. The transfer menu moves ONE complete paragraph to '
        'the END of another existing body group without changing any paragraph, label, display '
        'hint, fact ID or meaning reference. The supported opening stays in place. The measured '
        'page counts assume the CURRENT titles. Geometry is not semantic compatibility: judge '
        'the complete source-bound copy, transitions and every meaning carried by the original '
        'group headings before choosing. Do not select an incoherent transfer merely to fit. '
        'For a coherent transfer, select its ID and provide short faithful source_title and '
        'destination_title if needed to accurately describe the resulting groups. Null keeps '
        'the original title. Retain all necessary scope/qualifications carried by both headings; '
        'titles may introduce no unsupported claim. Changed titles are measured again and may '
        'still fail the page cap. If no transfer is semantically suitable, choose keep and use '
        'replacement for ALL revised pages in this SAME response, or leave replacement null to '
        'refuse. Never mix a transfer with replacement or title edits with keep. This selection '
        'grants no approval: fresh independent source and per-meaning review remain mandatory.')
    messages.insert(-1, untrusted_document_message(json.dumps(dict(
        target_physical_pages=review.max_intro_slides, transfer_options=choices), ensure_ascii=False)))
    try:
        wire_schema = writer_schema(response_schema)
        response = gateway.generate_structured(messages, wire_schema, stage='presentation',
            allow_repair=False, cancelled=cancelled)
        response = wire_schema.model_validate(response.model_dump())
        if response.choice == 'keep':
            if response.source_title is not None or response.destination_title is not None:
                raise ValueError('Keep cannot edit allocation titles')
            if response.replacement is None:
                revised = draft.model_copy(deep=True)
            else:
                patch, _ = bind_writer_copy(response.replacement, patch_schema)
                revised = apply_layout_patch(draft, patch, schema)
        else:
            if response.replacement is not None:
                raise ValueError('Allocation cannot also replace pages')
            selected = choices[response.choice]
            revised = transferred_draft(draft, selected['source'], selected['item'], selected['destination'])
            for field, index in [('source_title', selected['source']), ('destination_title', selected['destination'])]:
                title = getattr(response, field)
                if title is not None:
                    revised.pages[index].title = title
            revised = schema.model_validate(revised.model_dump(mode='json'))
    except Exception:
        audit['status'] = 'failed'
        raise
    audit.update(status='selected', response=response.model_dump(mode='json'))
    return revised
