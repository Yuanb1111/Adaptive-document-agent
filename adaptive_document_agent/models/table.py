"""Extracted table models with row-level page provenance."""

from pydantic import BaseModel, Field
from typing import Literal


class TableRow(BaseModel):
    cells: list[str | None]
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None
    column_periods: list[str | None] = Field(default_factory=list)
    indent_level: int = 0
    is_section_header: bool = False
    is_subtotal: bool = False
    is_deduction: bool = False
    alignment_status: Literal["resolved", "ambiguous"] = "resolved"


class ExtractedTable(BaseModel):
    table_id: str
    page: int = Field(ge=1)
    headers: list[str] = Field(default_factory=list)
    column_periods: list[str | None] = Field(default_factory=list)
    column_types: list[str] = Field(default_factory=list)  # amount, percentage, ratio, days, count, unknown
    column_currencies: list[str | None] = Field(default_factory=list)
    column_scales: list[float | None] = Field(default_factory=list)
    table_title: str | None = None
    unit_header: str | None = None
    section_path: list[str] = Field(default_factory=list)
    rows: list[TableRow] = Field(default_factory=list)
    raw_cells: list[list[str | None]] = Field(default_factory=list)
    raw_header_lines: list[str] = Field(default_factory=list)
    raw_body_lines: list[str] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    default_unit: str | None = None
    default_raw_unit: str | None = None
    default_unit_scale: float | None = None
    default_currency: str | None = None
    context_label: str | None = None
    continued_from: str | None = None
    continues_as: str | None = None
    warnings: list[str] = Field(default_factory=list)
