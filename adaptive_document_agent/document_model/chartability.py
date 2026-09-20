"""Multi-factor chartability scoring and validation for metric series."""

from __future__ import annotations

from dataclasses import dataclass

from adaptive_document_agent.models import Observation


from adaptive_document_agent.document_model.period_semantic_validator import extract_period_basis
from adaptive_document_agent.document_model.series import metric_key


@dataclass(frozen=True)
class ChartabilityResult:
    status: str  # 'HIGH', 'MEDIUM', 'LOW', 'INVALID'
    score: float  # 0.0 - 1.0
    reasons: list[str]
    is_chartable: bool


def score_chartability(series: list[Observation]) -> ChartabilityResult:
    """Evaluate whether a series is trustworthy and meaningful for visualization."""
    if not series:
        return ChartabilityResult(status="INVALID", score=0.0, reasons=["Empty series"], is_chartable=False)

    reasons: list[str] = []

    # 1. Observation count check
    if len(series) < 2:
        return ChartabilityResult(status="INVALID", score=0.0, reasons=["Fewer than 2 observations in series"], is_chartable=False)

    # 2. Numeric validity
    numeric_values = [o.value for o in series if o.value is not None]
    if len(numeric_values) < len(series):
        reasons.append("Series contains observations without numeric values")
        return ChartabilityResult(status="INVALID", score=0.0, reasons=reasons, is_chartable=False)

    # 3. Unit family coherence per metric
    for metric_name in {metric_key(o) for o in series}:
        m_obs = [o for o in series if metric_key(o) == metric_name]
        m_units = {getattr(o, "unit_family", None) or o.unit for o in m_obs}
        m_units = {u for u in m_units if u and u not in ("generic", "unknown")}
        if len(m_units) > 1:
            reasons.append(f"Mixed unit families for metric '{metric_name}': {m_units}")
            return ChartabilityResult(status="INVALID", score=0.0, reasons=reasons, is_chartable=False)

    # 4. Point uniqueness (must distinguish items along metric, period, or category axis)
    point_keys = [
        (
            metric_key(o),
            o.period,
            tuple(sorted(o.dimensions.items())) if o.dimensions else (),
            tuple(sorted(o.category_dimensions.items())) if getattr(o, "category_dimensions", None) else (),
            getattr(o, "entity", None),
        )
        for o in series
    ]
    if len(set(point_keys)) < len(series):
        reasons.append("Duplicate observations found with identical metric, period, and category dimensions")
        return ChartabilityResult(status="INVALID", score=0.0, reasons=reasons, is_chartable=False)

    # 5. Period type coherence (do not mix balance_sheet_date with fiscal_year or mixed bases within same metric)
    for metric_name in {metric_key(o) for o in series}:
        m_obs = [o for o in series if metric_key(o) == metric_name]
        period_types = {getattr(o, "period_type", "fiscal_year") for o in m_obs}
        if len(period_types) > 1 and "balance_sheet_date" in period_types and "fiscal_year" in period_types:
            reasons.append(f"Mixed balance sheet point-in-time dates with full fiscal year flow periods for '{metric_name}'")
            return ChartabilityResult(status="INVALID", score=0.0, reasons=reasons, is_chartable=False)
        bases = {extract_period_basis(o.period) for o in m_obs if o.period}
        bases.discard("generic")
        if len(bases) > 1:
            reasons.append(f"Mixed period bases {sorted(bases)} for '{metric_name}'")
            return ChartabilityResult(status="INVALID", score=0.0, reasons=reasons, is_chartable=False)

    # 6. Suspicious alignment & anomaly check
    suspicious = [o for o in series if getattr(o, "validation_status", "valid") == "suspicious_alignment" or getattr(o, "anomaly_notes", [])]
    if suspicious:
        notes = [note for o in suspicious for note in getattr(o, "anomaly_notes", [])]
        note_summary = "; ".join(notes[:2])
        reasons.append(f"Contains {len(suspicious)} suspicious observations: {note_summary}")
        return ChartabilityResult(status="INVALID", score=0.0, reasons=reasons, is_chartable=False)

    # 7. Plausibility for percentage metrics
    for o in series:
        u_fam = getattr(o, "unit_family", None) or o.unit
        if u_fam in ("percentage", "percent") and o.value is not None and abs(o.value) > 1000.0:
            reasons.append(f"Implausible percentage values detected: {o.value}% for {o.metric_original}")
            return ChartabilityResult(status="INVALID", score=0.0, reasons=reasons, is_chartable=False)

    # 8. Score calculation
    avg_extraction_conf = sum(o.confidence for o in series) / len(series)
    avg_semantic_conf = sum(getattr(o, "semantic_confidence", 1.0) for o in series) / len(series)
    length_score = min(len(series), 5) / 5.0
    score = (avg_extraction_conf * 0.45) + (avg_semantic_conf * 0.35) + (length_score * 0.20)

    if score >= 0.70 and len(series) >= 3:
        status = "HIGH"
    elif score >= 0.45:
        status = "MEDIUM"
    else:
        status = "LOW"

    return ChartabilityResult(
        status=status,
        score=score,
        reasons=reasons,
        is_chartable=status in ("HIGH", "MEDIUM"),
    )
