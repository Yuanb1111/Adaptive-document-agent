"""Canonical financial fact model representing verified numeric evidence."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class CanonicalFact(BaseModel):
    """Canonical financial fact with strict separation of raw, normalized, and display forms."""

    id: str
    raw_metric_name: str
    canonical_metric_name: str | None = None
    presentation_label: str = ""
    raw_value: str
    raw_unit: str | None = None
    normalized_value: float | None = None
    normalized_unit: str | None = None
    display_value: str = ""
    display_unit: str = ""
    currency: str | None = None
    period_type: str = "generic"  # fiscal_year, quarter, interim_period, ytd, balance_sheet_date, point_in_time, generic
    period_start: str | None = None
    period_end: str | None = None
    as_of_date: str | None = None
    audited_status: str = "unknown"  # audited, unaudited, unknown
    source_page: int | None = None
    source_excerpt: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    validation_status: str = "valid"  # valid, partially_valid, ambiguous, suspicious_alignment, invalid
    dimensions: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_observation(cls, obs: Any) -> CanonicalFact:
        """Create a CanonicalFact from an Observation."""
        page = None
        excerpt = None
        if obs.evidence:
            first_ev = obs.evidence[0]
            page = getattr(first_ev, "page", None)
            excerpt = getattr(first_ev, "text", None)

        norm_val = getattr(obs, "normalized_value", None)
        if norm_val is None:
            norm_val = obs.value

        norm_unit = getattr(obs, "normalized_unit", None)
        if norm_unit is None:
            norm_unit = obs.unit

        pres_label = getattr(obs, "presentation_label", "")
        if not pres_label:
            pres_label = obs.metric_canonical or obs.metric_original

        disp_val = getattr(obs, "display_value", "")
        if not disp_val and obs.value is not None:
            disp_val = str(obs.value)

        disp_unit = getattr(obs, "display_unit", "")
        if not disp_unit:
            disp_unit = obs.unit or ""

        return cls(
            id=obs.id,
            raw_metric_name=obs.metric_original,
            canonical_metric_name=obs.metric_canonical,
            presentation_label=pres_label,
            raw_value=obs.raw_value,
            raw_unit=obs.raw_unit,
            normalized_value=norm_val,
            normalized_unit=norm_unit,
            display_value=disp_val,
            display_unit=disp_unit,
            currency=obs.currency,
            period_type=getattr(obs, "period_type", "generic"),
            period_start=getattr(obs, "period_start", None),
            period_end=getattr(obs, "period_end", None),
            as_of_date=getattr(obs, "as_of_date", None),
            audited_status=getattr(obs, "audited_status", "unknown"),
            source_page=page,
            source_excerpt=excerpt,
            confidence=obs.confidence,
            validation_status=getattr(obs, "validation_status", "valid"),
            dimensions=getattr(obs, "dimensions", {}) or {},
        )
