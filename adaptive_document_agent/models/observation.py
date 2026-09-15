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

