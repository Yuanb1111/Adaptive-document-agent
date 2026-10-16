"""Exact many-part provenance and readable capacity for compact introductions."""
import json
from hashlib import sha256
from functools import lru_cache

from .source_quotes import split_literal_quote


def compact_digest(pages):
    values = [p.model_dump(mode='json') for p in pages]
    # A newly optional geometry field must not invalidate an independently
    # accepted historical draft that never proposed a semantic visual layout.
    # Real writer-selected structure remains part of the reviewed digest.
    for page in values:
        for item in page['items']:
            if item.get('display') is None:
                item.pop('display', None)
    return sha256(json.dumps(values,
                             sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def compact_item_errors(item, review, result):
    from pydantic import Field
    from .executive_brief import validate_executive_brief
    from .summary_validation import SummaryEvidenceItem
    from adaptive_document_agent.models.executive_brief import ExecutiveBrief, BriefQuote
    parts = {p.id: p for p in review.parts}
    refs, quotes, pages, evidence = [], [], set(), []
    errors = []
    for ref in item.source_refs:
        part = parts.get(ref.part_id)
        if part is None or part.role != 'content' or ref.fact_index >= len(part.facts):
            errors.append('Compact summary cites an unknown source fact')
            continue
        identity = (ref.part_id, ref.fact_index)
        if identity in refs:
            errors.append('Compact summary repeats a source fact reference')
        refs.append(identity)
        fact = part.facts[ref.fact_index]
        if fact.source_quote not in quotes:
            quotes.append(fact.source_quote)
        pages.update(fact.source_pages)
        for page in fact.source_pages:
            evidence.extend(BriefQuote(page=page,text=q) for q in split_literal_quote(fact.source_quote))
    expected_parts = list(dict.fromkeys(pid for pid, _ in refs))
    if (not refs or item.part_ids != expected_parts or item.source_pages != sorted(pages)
            or item.source_quote != '\n\n'.join(quotes)):
        errors.append('Compact summary changed its exact source-fact bindings')
    from .quantity_notation import literal_quantity_numbers
    if not literal_quantity_numbers(item.label+' '+item.text):
        # There is no numerical claim to resolve against every table cell.
        # Exact source ownership above and the mandatory independent meaning
        # review still apply to every part, including qualitative conditions.
        return errors
    if not errors:
        class CompactEvidenceItem(SummaryEvidenceItem):
            evidence: list[BriefQuote] = Field(min_length=1,max_length=512)
        brief = ExecutiveBrief(title='Summary', items=[CompactEvidenceItem(
            label=item.label,text=item.text,evidence=evidence)])
        errors.extend(validate_executive_brief(brief,result))
    return errors


def compact_continuation_errors(groups, review, result):
    errors = []
    for items in groups.values():
        ordered = sorted(items, key=lambda item: item.continuation_index)
        first = ordered[0]
        text = ''.join(item.text for item in ordered)
        fields = ('label', 'part_ids', 'source_refs', 'source_quote', 'source_pages',
                  'continuation_count', 'continuation_digest')
        if ([item.continuation_index for item in ordered] != list(range(first.continuation_count))
                or len(text) > 6000 or sha256(text.encode('utf-8')).hexdigest() != first.continuation_digest
                or any(any(getattr(item, field) != getattr(first, field) for field in fields) for item in ordered)):
            errors.append('Invalid compact Summary continuation provenance')
            continue
        # Validate the complete original claim so a currency/unit spanning a
        # layout boundary cannot be misinterpreted as a new isolated quantity.
        errors.extend(compact_item_errors(first.model_copy(update={'text': text}), review, result))
    return errors


def compact_title_errors(title):
    """Match the native template header's Arial 32, 8.91-inch, three-line limit."""
    from .text_capacity import wrap_copy
    return (['Compact summary title exceeds readable three-line capacity: ' + title]
            if len(wrap_copy(title, 8.91, 32)) > 3 else [])


def compact_body_capacity(title, slide_width, slide_height):
    """Reserve the same continuation header as render_profile's full-width path."""
    from .text_capacity import wrap_copy
    header_width = min(9.06, slide_width - .60) - .15
    lines = len(wrap_copy(title + ' (continued)', header_width, 32))
    top = max(1.45, .27 + lines * (32 / 72 * 1.22) + .15 + .12)
    return slide_height - 1.28 - top


def compact_heading_errors(label):
    """Match native full-width numbered paragraph headings before splitting copy."""
    from .text_capacity import wrap_copy
    from .pptx_export import _resolve_template_path
    path = _resolve_template_path()
    width, _ = _template_dimensions(str(path), path.stat().st_mtime_ns)
    return (['Compact summary paragraph heading exceeds readable two-line capacity: ' + label]
            if len(wrap_copy('00  ' + label, width - 1.3, 18)) > 2 else [])


def compact_layout_errors(pages):
    from .presentation_brief import BriefItem, _item_height, _heading_height, _copy_height, is_technical_copy
    from .slide_compositor import _lines
    from .pptx_export import _resolve_template_path
    path=_resolve_template_path()
    slide_width,slide_height=_template_dimensions(str(path),path.stat().st_mtime_ns)
    full_width=slide_width-1.3
    errors = []
    for page in pages:
        errors.extend(compact_title_errors(page.title))
        for item in page.items:
            errors.extend(compact_heading_errors(item.label))
        # Match the wide native text layout and reserve a wrapped template title.
        top = max(1.45,.27 + len(_lines(page.title,min(8.91,slide_width-.75),32)) * (32/72*1.22) + .27)
        capacity = compact_body_capacity(page.title, slide_width, slide_height)
        items = [BriefItem(i.label,i.text,i.source_pages) for i in page.items]
        needed = sum(_item_height(i,full_width) for i in items) + .12 * (len(items)-1)
        grid_fits = False
        if len(items) in {3,4}:
            columns,rows = (3,1) if len(items)==3 else (2,2)
            width = (full_width-.34*(columns-1))/columns
            height = (slide_height-1.20-top-.18*(rows-1))/rows
            grid_fits = all(len(_lines(i.title,width,18))<=2 and
                _heading_height(i.title,width)+.06+_copy_height(i.text,width,16)+.08<=height for i in items)
        if (needed > capacity and not grid_fits) or any(is_technical_copy(i.text) for i in items):
            errors.append('Compact summary page needs shorter complete claims: ' + page.id)
    return errors


@lru_cache(maxsize=4)
def _template_dimensions(path,revision):
    from pptx import Presentation
    deck=Presentation(path)
    return deck.slide_width.inches,deck.slide_height.inches
