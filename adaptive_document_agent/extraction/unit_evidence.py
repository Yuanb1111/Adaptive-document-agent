"""Resolve explicit cell units without leaking adjacent row declarations."""

import re
from dataclasses import dataclass

from adaptive_document_agent.models.table import ExtractedTable

from .normalizer import UnitDefaults, infer_unit_defaults


@dataclass(frozen=True)
class CellUnitDefaults(UnitDefaults):
    # Cached column metadata can have inherited the same scoped header as the
    # table metadata. Exclude both when that source belongs to another column.
    allow_column_defaults: bool = True


def cell_unit_defaults(table: ExtractedTable, row_index: int, column_label: str | None) -> CellUnitDefaults:
    """Prefer a row/column declaration, then an applicable source header.

    Retained source headers also recover qualifiers omitted by older cached
    table metadata. Never search other body rows for a cell's unit.
    """
    row_label = table.rows[row_index].cells[0] or ""
    for label in (row_label, column_label or ""):
        defaults = infer_unit_defaults(label)
        if defaults.currency:
            return CellUnitDefaults(**vars(defaults))

    scoped_elsewhere = False
    for line in reversed([*table.raw_header_lines, table.unit_header or ""]):
        defaults = infer_unit_defaults(line)
        if not defaults.currency:
            continue
        # "for ASP" qualifies just that column; "except for percentages"
        # remains a table-level declaration. Handle compact PDF text too.
        qualifier = re.search(r"(?:\bfor\s+|for(?=[A-Z]))([A-Za-z][A-Za-z ]*)", line)
        if qualifier and not re.search(r"(?i)except\s*for", line):
            target = re.sub(r"\s+", "", qualifier.group(1)).casefold()
            label = re.sub(r"\s+", "", column_label or "").casefold()
            if target != label:
                scoped_elsewhere = True
                continue
            return CellUnitDefaults(**vars(defaults), allow_column_defaults=False)
        return CellUnitDefaults(**vars(defaults), allow_column_defaults=not scoped_elsewhere)

    if scoped_elsewhere:
        return CellUnitDefaults(allow_column_defaults=False)
    return CellUnitDefaults(
        unit=table.default_unit,
        currency=table.default_currency,
        scale=table.default_unit_scale,
        raw_unit=table.default_raw_unit,
    )
