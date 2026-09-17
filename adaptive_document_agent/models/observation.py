"""Generic observation representation."""

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

    # Typed financial semantics
    semantic_type: str = "generic"  # monetary_amount, margin, ratio_share, multiple, days, count, growth_rate, generic
    unit_family: str = "generic"    # currency, percentage, multiple, days, count, generic
    display_unit: str = ""
    period_type: str = "generic"    # fiscal_year, interim_flow, balance_sheet_date, multi_year, generic
    period_start: str | None = None
    period_end: str | None = None
    as_of_date: str | None = None
    audited_status: str = "unknown"  # audited, unaudited, unknown

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
    def normalized_unit(self) -> str | None:
        return self.unit

    @property
    def period_label(self) -> str | None:
        return self.period

    @property
    def source_page(self) -> int | None:
        return self.evidence[0].page if self.evidence else None

    @property
    def source_section(self) -> str | None:
        return self.dimensions.get("section")

    @property
    def source_table(self) -> str | None:
        return self.evidence[0].table_id if self.evidence else None

    @property
    def source_text(self) -> str | None:
        return self.evidence[0].text if self.evidence else None

    @property
    def extraction_confidence(self) -> float:
        return self.confidence


FinancialObservation = Observation

