"""Verify a model's inclusion of corroborating source views without erasing IDs."""
import json

_META = {'column_role', 'table_context', 'section', 'period_basis'}
_GENERIC = {'total', 'subtotal', 'other', 'others', 'amount', 'value'}


def _fact(item):
    rows = {' '.join(e.row_label.casefold().split()) for e in item.evidence if e.row_label}
    if len(rows) != 1 or item.value is None or item.validation_status != 'valid' or item.anomaly_notes:
        return None
    row = next(iter(rows))
    if row in _GENERIC:
        return None
    dims = {k: v for k, v in {**item.dimensions, **item.category_dimensions}.items() if k not in _META}
    # A source row can be encoded as a category of its parent or as its metric.
    dims = {k: v for k, v in dims.items() if ' '.join(str(v).casefold().split()) != row}
    return (row, item.parent_section, item.value, item.raw_value, item.unit, item.raw_unit,
            item.unit_scale, item.currency, item.entity, item.period, item.period_basis,
            item.period_type, item.period_start, item.period_end, item.as_of_date,
            item.audited_status, item.ifrs_status, item.fact_type, json.dumps(dims, sort_keys=True))


def representation_links(group, selected):
    """All exact facts must match. This verifies inclusion, never chooses topics."""
    direct = {o.id: o for o in selected}
    facts = {}
    for item in selected:
        if (key := _fact(item)) is not None:
            facts.setdefault(key, []).append(item.id)
    links = {}
    for item in group:
        if item.id in direct:
            links[item.id] = [item.id]
        elif (key := _fact(item)) is not None and key in facts:
            links[item.id] = facts[key]
        else:
            return None
    return links or None
