"""Evidence-bound single-series calculations shared by slide enrichment and rendering."""

from dataclasses import dataclass
from math import isfinite
import re

from adaptive_document_agent.document_model import group_comparable_series, metric_key, score_chartability
from adaptive_document_agent.document_model.period_semantic_validator import classify_period
from adaptive_document_agent.models import Observation
from adaptive_document_agent.tools.growth import cagr
from adaptive_document_agent.validation.claim_validator import are_observations_compatible


@dataclass(frozen=True)
class PeriodChange:
    start_period: str
    end_period: str
    absolute_change: float
    percentage_change: float | None
    is_yoy: bool


@dataclass(frozen=True)
class SingleMetricAnalysis:
    observations: list[Observation]
    absolute_change: float
    percentage_change: float | None
    cagr: float | None
    changes: list[PeriodChange]
    peak: Observation
    trough: Observation
    turning_periods: list[str]
    is_percentage: bool


def _year_slot(period: str) -> tuple[int, str] | None:
    """Only explicit period labels establish annual intervals; never count rows as years."""
    compact = re.sub(r"\s+", "", period).upper().rstrip("*")
    match = re.fullmatch(r"(FY|[1-9]M|1[0-2]M|Q[1-4]|[12]H)?((?:19|20)\d{2})", compact)
    return (int(match[2]), match[1] or "FY") if match else None


def single_metric_analysis(observations: list[Observation]) -> SingleMetricAnalysis | None:
    """Return derived data only for one complete, compatible, evidenced series.

    Conflicting duplicates, missing values and mixed contexts reject enrichment
    instead of silently selecting the convenient subset of a slide's evidence.
    """
    if len(observations) < 2 or len({metric_key(o) for o in observations}) != 1:
        return None
    if any(o.value is None or not isfinite(o.value) or not o.period or not o.evidence
           or o.validation_status not in {"valid", "partially_valid"} for o in observations):
        return None
    groups = group_comparable_series(observations)
    if len(groups) != 1:
        return None
    series = groups[0]
    if {o.period for o in series} != {o.period for o in observations}:
        return None
    # Check all inputs, including records the grouping layer deduplicated.
    unit_aliases = {"percent": "percentage", "%": "percentage"}
    units = {unit_aliases.get(o.unit or "", o.unit or "") for o in observations}
    if len(units) != 1 or units <= {"", "unknown", "generic"}:
        return None
    if len({o.currency for o in observations}) != 1:
        return None
    if any(not are_observations_compatible(series[0], o)[0] for o in observations):
        return None
    if not score_chartability(series).is_chartable:
        return None
    periods = [classify_period(o.period) for o in series]
    slots = [_year_slot(p.clean_label) for p in periods]
    # Existing series grouping permits unknown labels for generic charts, but
    # growth calculations require positively identified, compatible periods.
    kinds = {
        ("quarter" if slot[1].startswith("Q") else "half_year" if slot[1].endswith("H") else slot[1])
        if slot else "date" if period.as_of_date else "unknown"
        for slot, period in zip(slots, periods)
    }
    if "unknown" in kinds or len(kinds) != 1:
        return None
    is_pct = series[0].unit in {"percent", "percentage", "%"} or series[0].unit_family == "percentage"
    values = [float(o.value) for o in series]
    if not isfinite(values[-1] - values[0]) or any(not isfinite(b - a) for a, b in zip(values, values[1:])):
        return None

    def rate(a: float, b: float) -> float | None:
        if is_pct or a <= 0 or b < 0:
            return None
        result = (b / a - 1) * 100
        return result if isfinite(result) else None

    annual_growth = None
    if all(s and s[1] == "FY" for s in slots) and all(v > 0 for v in values) and not is_pct:
        years = slots[-1][0] - slots[0][0]
        if years >= 2:
            candidate = cagr(values[0], values[-1], years)
            annual_growth = candidate if isfinite(candidate) else None
    changes = []
    for i, (left, right) in enumerate(zip(series, series[1:])):
        previous, current = slots[i], slots[i + 1]
        yoy = bool(previous and current and previous[1] == current[1] and current[0] - previous[0] == 1)
        changes.append(PeriodChange(left.period, right.period, values[i + 1] - values[i], rate(values[i], values[i + 1]), yoy))
    turns = [series[i].period for i in range(1, len(series) - 1)
             if (values[i] > values[i - 1] and values[i] > values[i + 1])
             or (values[i] < values[i - 1] and values[i] < values[i + 1])]
    return SingleMetricAnalysis(
        series, values[-1] - values[0], rate(values[0], values[-1]), annual_growth,
        changes, series[values.index(max(values))], series[values.index(min(values))], turns, is_pct,
    )
