"""Final bounded correction with measured alternatives and source-bound regrouping."""
import json
from typing import Literal

from pydantic import ConfigDict, create_model

from .prompting import untrusted_document_message
from .summary_writer_copy import address_only_copy, writer_schema, bind_writer_copy


def inline_group(page):
    """Retain every label, word and exact meaning quote in original author order."""
    if len(page.items) < 2:
        return None
    first = page.items[0]
    text = ' '.join((item.label + ': ' if index else '') + item.text
                    for index, item in enumerate(page.items))
    references, seen = [], set()
    for item in page.items:
        for ref in item.meaning_refs:
            key = ref.part_id, ref.meaning_index, ref.summary_quote
            if key not in seen:
                references.append(ref.model_dump(mode='json'))
                seen.add(key)
    data = page.model_dump(mode='json')
    data['items'] = [dict(first.model_dump(mode='json'), text=text,
        fact_ids=list(dict.fromkeys(fid for item in page.items for fid in item.fact_ids)),
        meaning_refs=references, display=None)]
    try:
        return type(page).model_validate(data)
    except ValueError:
        # Transport limits are not permission to truncate a complete paragraph.
        return None


def layout_choices(draft, catalog, review, expand):
    """Measure unchanged groups and full-copy alternatives; never choose meaning."""
    from .summary_theme_layout import pack_theme_pages, SummaryLayoutError
    choices = {}
    minimum = 0
    for index, page in enumerate(draft.pages):
        def measure(candidate):
            probe = draft.model_copy(update={'pages': [candidate]})
            return len(pack_theme_pages(expand(probe, catalog, review)))
        try:
            original_count = measure(page)
        except (SummaryLayoutError, ValueError):
            return {}
        best = original_count
        alternative = inline_group(page) if getattr(page, 'placement', 'body') == 'body' else None
        if alternative is not None:
            try:
                count = measure(alternative)
            except (SummaryLayoutError, ValueError):
                count = original_count
            if count < original_count:
                choices[f'group_{index}'] = dict(index=index, original_pages=original_count,
                    inline_pages=count, page=alternative)
                best = count
        if getattr(page, 'placement', 'body') == 'body':
            minimum += best
    # A menu which cannot meet the budget does not deserve an extra model call.
    return choices if review.max_intro_slides is not None and minimum <= review.max_intro_slides else {}


def choose_layout(gateway, draft, catalog, review, record, choices, schema, *, cancelled=None,
                  instruction=''):
    """Use the final correction for an exact option OR model-authored regrouping."""
    from concurrent.futures import CancelledError
    if cancelled is not None and cancelled.is_set():
        raise CancelledError('Summary layout choice cancelled')
    from .summary_layout_patch import layout_patch_schema, layout_patch_messages, apply_layout_patch
    patch_schema = layout_patch_schema(schema)
    response_schema = create_model('SummaryLayoutChoice', __config__=ConfigDict(extra='forbid'),
        **{key: (Literal['keep', 'inline'], ...) for key in choices},
        replacement=(patch_schema | None, None))
    menu = {key: dict(original_physical_pages=row['original_pages'],
        inline_physical_pages=row['inline_pages'],
        inline_page=address_only_copy(row['page'].model_dump(mode='json')))
        for key, row in choices.items()}
    audit = record['lossless_layout_choice'] = dict(menu=menu, status='pending',
        semantic_approval=False, additional_rewrite_round=False, replacement_allowed=True)
    context = dict(errors=[], compression_round=2, compression_round_limit=2)
    context.update(record)
    messages = layout_patch_messages(draft, catalog, context, instruction,
                                    audience_selected=review.audience_part_ids is not None)
    messages[0]['content'] = messages[0]['content'].replace(
        'Return ONLY pages under the schema;',
        'Return the requested group choices and optional replacement under the schema;')
    messages[0]['content'] += (
        ' This is the FINAL existing layout correction, with no further content attempt. Each inline '
        'option retains the existing group title, first label, all body text, subsequent labels as '
        'literal inline labels, all evidence and exact meaning quotations, in original order. '
        'It replaces paragraph boundaries and display hints, never words or facts. Judge whether '
        'each option remains coherent and preserves conditions, scope and relationships in the '
        'supported original text. When a suitable combination meets the measured total budget, '
        'choose inline/keep and set replacement to null; groups absent from the menu stay unchanged. '
        'If the offered combination is unsuitable, use THIS SAME response to supply replacement '
        'with ALL revised logical pages, and set every group choice to keep. Reorganize coherently, '
        'shorten faithful headings or synthesize compatible assertions using the full measured '
        'feedback and owned sources. The unchanged over-budget draft cannot succeed. Preserve '
        'every required meaning, qualification, fact ID and protected identity; do not choose an '
        'incoherent combination merely to fit. All keep with replacement null remains a valid '
        'refusal if no faithful solution is possible. A choice grants no semantic approval: the '
        'complete copy still requires independent source and meaning review.')
    messages.insert(-1, untrusted_document_message(json.dumps(dict(
        target_physical_pages=review.max_intro_slides, alternatives=menu), ensure_ascii=False)))
    try:
        wire_schema = writer_schema(response_schema)
        response = gateway.generate_structured(messages, wire_schema, stage='presentation',
            allow_repair=False, cancelled=cancelled)
        # Validate even custom/mock gateways: unknown choices cannot mutate copy.
        response = wire_schema.model_validate(response.model_dump())
        decisions = {key: getattr(response, key) for key in choices}
        if response.replacement is not None:
            if any(value != 'keep' for value in decisions.values()):
                raise ValueError('Layout replacement cannot also select inline patches')
            patch, count = bind_writer_copy(response.replacement, patch_schema)
            revised = apply_layout_patch(draft, patch, schema)
            audit.update(mode='replacement', replacement=patch.model_dump(mode='json'),
                         writer_reference_count=count)
        else:
            data = draft.model_dump(mode='json')
            for key, decision in decisions.items():
                if decision == 'inline':
                    row = choices[key]
                    data['pages'][row['index']] = row['page'].model_dump(mode='json')
            revised = schema.model_validate(data)
            audit['mode'] = 'exact_choices'
    except Exception:
        audit['status'] = 'failed'
        raise
    audit.update(status='selected', response=decisions)
    return revised
