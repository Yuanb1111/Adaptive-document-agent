"""Validated categorical matrices for editable composition charts, without invented totals."""

from dataclasses import dataclass
from math import isclose, isfinite
import re

from adaptive_document_agent.document_model import metric_key, period_sort_key
from adaptive_document_agent.models import ChartPlan, Observation
from adaptive_document_agent.validation.claim_validator import are_observations_compatible
from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric

COMPOSITION_TYPES = {"stacked_bar", "stacked_percent", "doughnut"}
_META = {"table_context", "section", "period_basis", "column_role"}


@dataclass(frozen=True)
class CompositionData:
    periods: list[str]
    categories: list[str]
    values: list[list[float]]  # category x period, in normalized observation units
    is_percentage: bool
    source_pages: list[int]


def composition_data(plan: ChartPlan, observations: list[Observation], totals: list[Observation] | None = None) -> CompositionData:
    """Reject partial matrices, mixed contexts, negatives and unproved denominators.

    Missing categories are not zeroes. Normalising a selected subset into 100%
    would misrepresent its coverage, so amount shares require reconciled totals.
    """
    dimension = plan.series_dimension or plan.x_dimension
    if not dimension or len(observations) < 2:
        raise ValueError("Composition charts require an explicit category dimension and retained values.")
    if {o.id for o in observations} != set(plan.observation_ids):
        raise ValueError("Composition chart references missing observations.")
    first = observations[0]
    units = {"percent": "percentage", "%": "percentage"}
    unit = units.get(first.unit or "", first.unit or "")
    if unit in {"", "unknown", "generic", "multiple", "days"}:
        raise ValueError("Composition requires compatible additive amounts, counts or percentage shares.")
    contexts = set()
    points = {}
    for obs in observations:
        if (obs.value is None or not isfinite(obs.value) or obs.value < 0 or not obs.period
                or not obs.evidence or obs.validation_status not in {"valid", "partially_valid"}
                or obs.anomaly_notes or obs.row_operator != "additive"):
            raise ValueError("Composition contains missing, negative, ungrounded or invalid values.")
        if (metric_key(obs) != metric_key(first) or units.get(obs.unit or "", obs.unit or "") != unit
                or obs.currency != first.currency or not are_observations_compatible(first, obs)[0]):
            raise ValueError("Composition mixes metrics, units, currencies or reporting periods.")
        dims = {**obs.dimensions, **obs.category_dimensions}
        category = dims.get(dimension)
        if not category:
            raise ValueError("Composition category is missing.")
        contexts.add((obs.entity, obs.source_section, obs.ifrs_status, obs.period_basis,
                      tuple(sorted((k, v) for k, v in dims.items() if k not in _META | {dimension}))))
        key = (obs.period, category)
        if key in points:
            raise ValueError("Composition has duplicate period/category cells.")
        points[key] = float(obs.value)
    if len(contexts) != 1:
        raise ValueError("Composition mixes entities or non-axis dimensions.")
    periods = sorted({p for p, _ in points}, key=period_sort_key)
    categories = sorted({c for _, c in points}, key=str.casefold)
    if not 2 <= len(categories) <= 8:
        raise ValueError("Composition requires two to eight readable categories; use a comparison table otherwise.")
    if plan.chart_type == "doughnut" and len(periods) != 1:
        raise ValueError("Doughnut charts must describe exactly one period.")
    if plan.chart_type != "doughnut" and len(periods) < 2:
        raise ValueError("Stacked time-series charts require at least two comparable periods.")
    if len(points) != len(periods) * len(categories):
        raise ValueError("Composition is incomplete across periods; missing categories cannot be filled with zero.")
    matrix = [[points[p, c] for p in periods] for c in categories]
    sums = [sum(row[i] for row in matrix) for i in range(len(periods))]
    if any(not isfinite(s) or s <= 0 for s in sums):
        raise ValueError("Composition totals must be finite and positive.")
    is_pct = unit == "percentage"
    if is_pct and classify_metric(first.metric_original).semantic_type in {"margin", "growth_rate"}:
        raise ValueError("Independent margins or growth rates are not additive composition shares.")
    if any(c.strip().casefold() in {"total", "grand total", "subtotal", "all", "合计", "总计"} for c in categories):
        raise ValueError("Aggregate totals cannot be plotted as components alongside their parts.")
    if plan.chart_type in {"stacked_percent", "doughnut"}:
        if is_pct:
            if any(not isclose(s, 100, abs_tol=0.5) for s in sums):
                raise ValueError("Reported percentage shares do not reconcile to 100% within rounding tolerance.")
        else:
            totals = totals or []
            if not plan.total_observation_ids or {o.id for o in totals} != set(plan.total_observation_ids):
                raise ValueError("Amount-based part-to-whole charts require retained total observations.")
            if len(totals) != len(periods) or {o.period for o in totals} != set(periods):
                raise ValueError("Composition totals must match every displayed period exactly once.")
            for total in totals:
                total_dims = {**total.dimensions, **total.category_dimensions}
                scope = (total.entity, total.source_section, total.ifrs_status, total.period_basis,
                         tuple(sorted((k, v) for k, v in total_dims.items() if k not in _META | {dimension})))
                total_name = re.sub(r"^(?:total\s+|aggregate\s+|总计[:：\s]*|合计[:：\s]*)", "", metric_key(total))
                component_name = re.sub(r"^(?:total\s+|aggregate\s+|总计[:：\s]*|合计[:：\s]*)", "", metric_key(first))
                comparable_total = total.model_copy(update={"metric_original": first.metric_original, "metric_canonical": first.metric_canonical})
                if (total.id in plan.observation_ids or total.value is None or not isfinite(total.value)
                        or not total.evidence or total.validation_status not in {"valid", "partially_valid"}
                        or total.anomaly_notes or total.unit != first.unit or total.currency != first.currency
                        or scope not in contexts or total_name != component_name or not are_observations_compatible(first, comparable_total)[0]
                        or not isclose(sums[periods.index(total.period)], total.value, rel_tol=0.005, abs_tol=1e-9)):
                    raise ValueError("Composition does not reconcile to its compatible evidenced total.")
    return CompositionData(periods, categories, matrix, is_pct,
        sorted({e.page for o in [*observations, *(totals or [])] for e in o.evidence}))
