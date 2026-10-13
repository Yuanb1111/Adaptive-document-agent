"""Reconcile redundant boundary ownership only when every fact keeps its quote."""


def reconcile_contained_spans(response, blocks, record):
    """Retain both model-selected topics, all facts and the exact source union.

    A broad part can repeat a prefix/suffix assigned to a narrower part even
    though its facts cite only the other lines. Remove that redundant ownership
    after a model correction was attempted. Crossing quotes, interior overlaps,
    empty facts and out-of-source ranges still require semantic repartitioning.
    """
    lengths = {b.id: len(b.text.splitlines(keepends=True)) for b in blocks}
    parts = list(response.parts)
    changes = []
    for index, parent in enumerate(parts):
        if parent.role != 'content' or not parent.facts:
            continue
        for child_index, child in enumerate(parts):
            if (index == child_index or child.block_id != parent.block_id
                    or child.role != 'content' or not child.facts
                    or not 1 <= parent.start_line <= child.start_line <= child.end_line <= parent.end_line <= lengths.get(parent.block_id, 0)
                    or not all(child.start_line <= f.quote_start_line <= f.quote_end_line <= child.end_line for f in child.facts)):
                continue
            if parent.start_line == child.start_line and child.end_line < parent.end_line:
                start, end = child.end_line + 1, parent.end_line
            elif parent.end_line == child.end_line and parent.start_line < child.start_line:
                start, end = parent.start_line, child.start_line - 1
            else:
                continue
            if not all(start <= f.quote_start_line <= f.quote_end_line <= end for f in parent.facts):
                continue
            changes.append(dict(original_part=parent.model_dump(mode='json'),
                start_line=start, end_line=end, other_owner=child.model_dump(mode='json')))
            parent = parent.model_copy(update={'start_line': start, 'end_line': end})
            parts[index] = parent
    if changes:
        record['source_ownership_reconciliation'] = changes
    return response.model_copy(update={'parts': parts})
