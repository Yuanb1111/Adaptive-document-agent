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
    row_defaults = infer_unit_defaults(row_label)
    column_defaults = infer_unit_defaults(column_label or '')
    # A row-specific currency/denominator overrides table scaling. A bare
    # currency COLUMN still belongs to the explicit table unit declaration.
    if row_defaults.currency:
        return CellUnitDefaults(**vars(row_defaults))
    if column_defaults.currency and column_defaults.scale:
        return CellUnitDefaults(**vars(column_defaults))

    scoped_elsewhere = False
    lines = [*table.raw_header_lines, table.unit_header or '']
    scale_only = next((infer_unit_defaults(line) for line in reversed(lines)
        if re.fullmatch(r"(?i)\s*\(?\s*in\s+(?:thousands?|millions?|billions?)(?:\s*,?\s*except\s+(?:for\s+)?percentages)?\s*\)?\s*",line)),None)
    for line in reversed(lines):
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
        if scale_only and not defaults.scale:
            # Both phrases are literal source header declarations. Preserve
            # their provenance instead of inheriting a nearby narrative scale.
            return CellUnitDefaults(unit=defaults.unit,currency=defaults.currency,
                scale=scale_only.scale,raw_unit=defaults.raw_unit+'; '+next(line for line in reversed(lines)
                    if infer_unit_defaults(line)==scale_only),allow_column_defaults=False)
        return CellUnitDefaults(**vars(defaults), allow_column_defaults=not scoped_elsewhere)

    if scoped_elsewhere:
        return CellUnitDefaults(allow_column_defaults=False)
    if column_defaults.currency and table.default_currency not in (None,column_defaults.currency):
        return CellUnitDefaults(**vars(column_defaults),allow_column_defaults=False)
    return CellUnitDefaults(
        unit=table.default_unit,
        currency=table.default_currency,
        scale=table.default_unit_scale,
        raw_unit=table.default_raw_unit,
    )
