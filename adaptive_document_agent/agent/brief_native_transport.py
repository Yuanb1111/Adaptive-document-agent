"""Compact exact source spellings for the first draft, without another model call."""
from copy import deepcopy
import json
from itertools import zip_longest

from .brief_native_quantities import native_quantity_options
from .brief_audit_scope import audit_status_options


def _compact(option):
    bases = option.get('literal_basis', [''])
    suffix = ' per ' + bases[0] if len(bases) == 1 and bases[0] else ''
    value = {'amount_text': option['amount_text'] + suffix}
    if len(bases) > 1:
        value['source_bases'] = bases  # Ambiguity stays explicit; never choose one.
    if option.get('magnitude_option'):
        magnitude = deepcopy(option['magnitude_option'])
        magnitude['amount_text'] += suffix
        magnitude['quantity_representation']['quantity_text'] += suffix
        value['magnitude_option'] = magnitude
    return value


def _coalesce_statuses(statuses):
    """Combine row names only when every column/status address is identical."""
    groups = {}
    for status in statuses:
        address = {key: value for key, value in status.items() if key != 'source_row_labels'}
        key = json.dumps(address, ensure_ascii=False, sort_keys=True)
        group = groups.setdefault(key, {**address, 'source_row_labels': []})
        group['source_row_labels'].extend(label for label in status['source_row_labels']
                                        if label not in group['source_row_labels'])
    return sorted(groups.values(), key=lambda status: status['status'] == 'unknown')


def source_quantity_options(result, excerpts, blocks, *, character_limit=18000):
    """Pack bounded literal options incrementally rather than dropping a whole page.

    Every source block remains in the original evidence directory. These are
    optional transport spellings, not a semantic selection or new evidence.
    """
    candidates = {}
    for page in excerpts:
        refs = [key for key, block in blocks.items() if block['page'] == page]
        seen = set()
        for start in range(0, len(refs), 3):
            group = refs[start:start + 4]
            original = {'items': [{'label': 'Source values', 'text': 'Source-native values.',
                                  'evidence': [blocks[key] for key in group]}]}
            options = native_quantity_options(original, {0: []}, result, excerpts).get('item_0', [])
            row = {'page': page, 'evidence_refs': group, 'quantities': []}
            from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
            try:
                item = ExecutiveBriefItem.model_validate(original['items'][0])
                # Assurance belongs to an exact table row and column. Keep its
                # address even when another measure in the same period has a
                # different status; a period-only pair would erase that scope.
                statuses = audit_status_options(item, result)
            except ValueError:
                statuses = []
            quantities = []
            for option in options:
                compact = _compact(option)
                key = json.dumps(compact, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    continue
                quantities.append(compact)
                seen.add(key)
            queue = candidates.setdefault(page, [])
            # Interleave both aids rather than letting a large assurance grid
            # consume every amount slot (or amounts erase all qualifications).
            for status, quantity in zip_longest(_coalesce_statuses(statuses), quantities):
                if status is not None:
                    queue.append((row, 'source_period_statuses', status))
                if quantity is not None:
                    queue.append((row, 'quantities', quantity))
    rows, positions = [], {}
    # Every source page gets a turn before any page receives another entry.
    # Nothing omitted by this optional budget gains evidence or assurance.
    for batch in zip_longest(*candidates.values()):
        for entry in batch:
            if entry is None:
                continue
            base, field, value = entry
            key = (base['page'], tuple(base['evidence_refs']))
            index = positions.get(key, len(rows))
            previous = rows[index] if index < len(rows) else base
            proposed = {**previous, field: [*previous.get(field, []), value]}
            packed = [*rows[:index], proposed, *rows[index + 1:]]
            if len(json.dumps(packed, ensure_ascii=False)) <= character_limit:
                positions[key] = index
                rows = packed
    return rows
