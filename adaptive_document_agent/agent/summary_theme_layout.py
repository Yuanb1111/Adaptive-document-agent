"""Pack whole authored items into readable pages without changing their claims."""
from adaptive_document_agent.models.summary import SummarySlideItem, SummarySlidePage
from adaptive_document_agent.services.compact_summary import (
    compact_heading_errors, compact_layout_errors, compact_title_errors)


def split_compact_item(text, title, identity, values):
    """Lossless continuation layout before the final slide-item schema applies."""
    title_errors = compact_title_errors(title)
    if title_errors:
        # Reducing paragraph length cannot repair the native title box. Keep
        # all body copy intact and let the bounded title repair handle it.
        raise SummaryLayoutError('; '.join(title_errors))
    heading_errors = compact_heading_errors(values['label'])
    if heading_errors:
        raise SummaryLayoutError('; '.join(heading_errors))
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


def pack_theme_items(page: SummarySlidePage, items: list[SummarySlideItem]) -> list[SummarySlidePage]:
    """Find the fewest readable pages for one complete ordered authored group.

    Geometry is not monotone in item count: three/four paragraphs can fit the
    native grid even when two cannot fit the vertical layout. Consider every
    contiguous one-to-four-item candidate instead of ending a page at the
    first overflow. No paragraph, evidence binding or author order is changed.
    """
    if not items:
        return []
    title_errors = compact_title_errors(page.title)
    if title_errors:
        raise SummaryLayoutError('; '.join(title_errors))
    for item in items:
        heading_errors = compact_heading_errors(item.label)
        if heading_errors:
            raise SummaryLayoutError('; '.join(heading_errors))
        if compact_layout_errors([page.model_copy(update={'items': [item]})]):
            raise SummaryLayoutError('A theme paragraph needs shorter complete model-authored copy: ' + item.label)
    count = len(items)
    minimum_pages = [count + 1] * count + [0]
    # Among equally short valid paginations, balance complete copy instead of
    # stranding a short final paragraph after a dense multi-column page.
    from adaptive_document_agent.services.presentation_brief import BriefItem, _item_height
    from adaptive_document_agent.services.compact_summary import _template_dimensions
    from adaptive_document_agent.services.pptx_export import _resolve_template_path
    path = _resolve_template_path()
    width, _ = _template_dimensions(str(path), path.stat().st_mtime_ns)
    loads = [0.0]
    for item in items:
        loads.append(loads[-1] + _item_height(BriefItem(item.label, item.text, []), width - 1.3))
    balance = [float('inf')] * count + [0.0]
    next_offsets = [0] * count
    for start in range(count - 1, -1, -1):
        # Page count takes precedence. Only a geometric tie can rebalance
        # whole paragraphs, and exact ties retain the longer opening page.
        for end in range(min(count, start + 4), start, -1):
            probe = page.model_copy(update={'items': items[start:end]})
            if compact_layout_errors([probe]):
                continue
            candidate_pages = 1 + minimum_pages[end]
            candidate_balance = (loads[end] - loads[start]) ** 2 + balance[end]
            if (candidate_pages, candidate_balance) < (minimum_pages[start], balance[start]):
                minimum_pages[start], next_offsets[start] = candidate_pages, end
                balance[start] = candidate_balance
    packed, start = [], 0
    while start < count:
        end = next_offsets[start]
        packed.append(page.model_copy(update={'items': items[start:end]}))
        start = end
    return packed


def pack_theme_pages(pages: list[SummarySlidePage]) -> list[SummarySlidePage]:
    """Pack each supplied group independently; never merge separate headings."""
    packed = [packed_page for page in pages for packed_page in pack_theme_items(page, page.items)]
    return [page.model_copy(update={'id': f'theme_page_{i+1}'}) for i, page in enumerate(packed)]


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
