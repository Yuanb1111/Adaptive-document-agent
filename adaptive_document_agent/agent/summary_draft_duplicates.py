"""Remove exact duplicate copy bound to the same facts inside a logical group."""


def deduplicate_draft(draft, audit):
    revised = draft.model_copy(deep=True)
    for group_index, page in enumerate(revised.pages):
        seen, retained = {}, []
        for item_index, item in enumerate(page.items):
            key = (item.text, tuple(sorted(item.fact_ids)))
            if key in seen:
                audit.setdefault('identical_copy_reconciliation', []).append(dict(
                    group_index=group_index, item_index=item_index,
                    retained_item_index=seen[key], original_item=item.model_dump(mode='json')))
            else:
                seen[key] = item_index
                retained.append(item)
        page.items = retained
    return revised
