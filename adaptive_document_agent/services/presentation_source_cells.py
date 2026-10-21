"""Compact same-source table layouts and literal nonnumeric source cells."""
import re
from .presentation_evidence import evidence_groups


def compact_source_table(items):
    """Choose layout only; the model already selected the measures together."""
    groups = evidence_groups(items)
    if not 4 <= len(groups) <= 6 or any(not o.period for o in items):
        return False
    from .presentation_period_scope import _period
    bases = {_period(o)[0] if _period(o) is not None else None for o in items}
    if len(bases) != 1 or None in bases:
        return False
    if len({(o.unit, o.raw_unit, o.currency, o.entity) for o in items}) != 1:
        return False
    periods = {o.period for o in items}
    if not 1 <= len(periods) <= 5:
        return False
    tables = [{e.table_id for o in group for e in o.evidence if e.table_id} for group in groups]
    if not set.intersection(*tables):
        return False
    for group in groups:
        for period in {o.period for o in group}:
            if len({o.value for o in group if o.period == period}) != 1:
                return False
    return True


def literal_empty_source_cell(group, period, result):
    """Copy a uniquely bound source dash/N/A; never interpret it as zero."""
    period = period.removesuffix('*')
    locations = {(e.page, e.table_id, e.row_label) for o in group for e in o.evidence
                 if e.table_id and e.row_label}
    values = set()
    norm = lambda s: ' '.join(str(s or '').split()).rstrip(':').casefold()
    for page in result.document.pages:
        for table in page.tables:
            labels = {label for p, tid, label in locations
                      if p == page.page_number and tid == table.table_id}
            if not labels:
                continue
            columns = [i for i, p in enumerate(table.column_periods) if p == period]
            if len(columns) != 1:
                continue  # Repeated amount/% columns need additional scope proof.
            for row in table.rows:
                if row.alignment_status == 'ambiguous' or not row.cells:
                    continue
                if norm(row.cells[0]) not in {norm(label) for label in labels}:
                    continue
                value = row.cells[columns[0]] if columns[0] < len(row.cells) else None
                if value is not None:
                    values.add(str(value).strip())
    if len(values) == 1 and re.fullmatch(r'[—–-]|N/?A', next(iter(values)), re.I):
        return next(iter(values))
    return None
