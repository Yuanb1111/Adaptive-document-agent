"""Compact exact source spellings for the first draft, without another model call."""
from copy import deepcopy
import json

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


def source_quantity_options(result, excerpts, blocks, *, character_limit=18000):
    """Pack bounded literal options incrementally rather than dropping a whole page.

    Every source block remains in the original evidence directory. These are
    optional transport spellings, not a semantic selection or new evidence.
    """
    rows = []
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
            if statuses:
                scoped = {**row, 'source_period_statuses': statuses}
                if len(json.dumps([*rows, scoped], ensure_ascii=False)) <= character_limit:
                    row = scoped
                # These are optional transport aids. If the complete addresses
                # cannot fit, retain the original evidence blocks and numeric
                # options rather than sending misleading period-only statuses.
            for option in options:
                compact = _compact(option)
                key = json.dumps(compact, ensure_ascii=False, sort_keys=True)
                if key in seen:
                    continue
                proposed = {**row, 'quantities': [*row['quantities'], compact]}
                if len(json.dumps([*rows, proposed], ensure_ascii=False)) > character_limit:
                    continue
                row = proposed
                seen.add(key)
            if (row['quantities'] or row.get('source_period_statuses')) and len(
                    json.dumps([*rows, row], ensure_ascii=False)) <= character_limit:
                rows.append(row)
    return rows
