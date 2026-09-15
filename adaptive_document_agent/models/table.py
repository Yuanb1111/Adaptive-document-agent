"""Extracted table models with row-level page provenance."""

from pydantic import BaseModel, Field


class TableRow(BaseModel):
    cells: list[str | None]
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None
    column_periods: list[str | None] = Field(default_factory=list)


class ExtractedTable(BaseModel):
    table_id: str
    page: int = Field(ge=1)
    headers: list[str] = Field(default_factory=list)
    column_periods: list[str | None] = Field(default_factory=list)
    rows: list[TableRow] = Field(default_factory=list)
    raw_cells: list[list[str | None]] = Field(default_factory=list)
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
