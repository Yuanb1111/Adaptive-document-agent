"""Pack whole authored items into readable pages without changing their claims."""
from adaptive_document_agent.models.summary import SummarySlidePage
from adaptive_document_agent.services.compact_summary import compact_layout_errors


def split_compact_item(text, title, identity, values):
    """Lossless continuation layout before the final slide-item schema applies."""
    from hashlib import sha256
    from adaptive_document_agent.models.summary import SummarySlideItem
    from .summary_editorial import split_editorial_copy
    limit = min(1200, len(text))
    while True:
        pieces = split_editorial_copy(text, limit=limit)
        items = [SummarySlideItem(text=piece, **values) for piece in pieces]
        if all(not compact_layout_errors([SummarySlidePage(id='probe', title=title,
                source_section=title, compact=True, items=[item])]) for item in items):
            break
        if limit <= 80:
            raise SummaryLayoutError('A paragraph cannot fit readable continuation layout: ' + values['label'])
        limit = max(80, int(limit * .75))
    if len(items) > 1:
        digest = sha256(text.encode('utf-8')).hexdigest()
        group = sha256((identity + ':' + digest).encode('utf-8')).hexdigest()
        for index, item in enumerate(items):
            item.continuation_group = group
            item.continuation_index = index
            item.continuation_count = len(items)
            item.continuation_digest = digest
    return items


class SummaryLayoutError(ValueError):
    """One complete paragraph cannot fit on an otherwise empty slide."""


def pack_theme_pages(pages: list[SummarySlidePage]) -> list[SummarySlidePage]:
    packed = []
    for page in pages:
        items = []
        for item in page.items:
            probe = page.model_copy(update={'items': items + [item]})
            if items and (len(items)>=4 or compact_layout_errors([probe])):
                packed.append(page.model_copy(update={'items':items}))
                items = []
            single = page.model_copy(update={'items':[item]})
            if compact_layout_errors([single]):
                raise SummaryLayoutError('A theme paragraph needs shorter complete model-authored copy: '+item.label)
            items.append(item)
        if items:
            packed.append(page.model_copy(update={'items':items}))
    return [page.model_copy(update={'id':f'theme_page_{i+1}'}) for i,page in enumerate(packed)]


def merge_identical_items(pages, review):
    """Deduplicate exact reviewed copy, preserving every independently accepted binding."""
    parts = {p.id: p for p in review.parts}
    seen, merged = {}, []
    for page in pages:
        items = []
        for source in page.items:
            key = (source.label, source.text)
            if key not in seen:
                item = source.model_copy(deep=True)
                seen[key] = item
                items.append(item)
                continue
            item = seen[key]
            refs = {(r.part_id, r.fact_index) for r in item.source_refs}
            item.source_refs.extend(r.model_copy() for r in source.source_refs
                                    if (r.part_id, r.fact_index) not in refs)
            item.part_ids = list(dict.fromkeys(r.part_id for r in item.source_refs))
            facts = [parts[r.part_id].facts[r.fact_index] for r in item.source_refs]
            item.source_quote = '\n\n'.join(dict.fromkeys(f.source_quote for f in facts))
            item.source_pages = sorted({p for f in facts for p in f.source_pages})
        if items:
            merged.append(page.model_copy(update={'items': items}))
    return merged
