"""Generic observation representation."""

from typing import Any
from pydantic import BaseModel, Field

from .evidence import SourceEvidence


class Observation(BaseModel):
    id: str
    metric_original: str
    metric_canonical: str | None = None
    value: float | None = None
    raw_value: str
    unit: str | None = None
    raw_unit: str | None = None
    unit_scale: float | None = None
    currency: str | None = None
    period: str | None = None
    entity: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    # Provenance and structural hierarchy
    source_table: str | None = None
    table_id: str | None = None
    row_id: int | None = None
    column_id: int | None = None
    category_dimensions: dict[str, str] = Field(default_factory=dict)
    parent_section: str | None = None
    row_operator: str = "additive"  # additive, subtractive (for "Less:" rows)
    semantic_confidence: float = 1.0
    chartability_status: str = "unassessed"  # high, medium, low, invalid
    anomaly_notes: list[str] = Field(default_factory=list)

    # Typed financial semantics
    semantic_type: str = "generic"  # monetary_amount, margin, ratio_share, multiple, days, count, growth_rate, generic
    unit_family: str = "generic"    # currency, percentage, multiple, days, count, generic
    display_unit: str = ""
    display_value: str = ""
    presentation_label: str = ""
    normalized_value: float | None = None
    normalized_unit: str | None = None
    period_type: str = "generic"    # fiscal_year, interim_flow, balance_sheet_date, multi_year, generic
    period_start: str | None = None
    period_end: str | None = None
    as_of_date: str | None = None
    audited_status: str = "unknown"  # audited, unaudited, unknown
    validation_status: str = "valid"  # valid, partially_valid, ambiguous, suspicious_alignment, invalid

    @property
    def source_label(self) -> str:
        return self.metric_original

    @property
    def canonical_name(self) -> str | None:
        return self.metric_canonical

    @property
    def numeric_value(self) -> float | None:
        return self.value

    @property
    def source_unit(self) -> str | None:
        return self.raw_unit

    @property
    def source_scale(self) -> float | None:
        return self.unit_scale

    @property
    def period_label(self) -> str | None:
        return self.period

    @property
    def source_page(self) -> int | None:
        return self.evidence[0].page if self.evidence else None

    @property
    def source_section(self) -> str | None:
        return self.parent_section or self.dimensions.get("section")

    @property
    def effective_table_id(self) -> str | None:
        return self.table_id or (self.evidence[0].table_id if self.evidence else None)

    @property
    def source_text(self) -> str | None:
        return self.evidence[0].text if self.evidence else None

    @property
    def extraction_confidence(self) -> float:
        return self.confidence

    def to_canonical_fact(self) -> Any:
        from .fact import CanonicalFact
        return CanonicalFact.from_observation(self)


FinancialObservation = Observation


