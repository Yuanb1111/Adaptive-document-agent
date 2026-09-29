"""Small, calculated chart captions for model-selected comparable series."""

from __future__ import annotations

import re

from adaptive_document_agent.document_model import period_sort_key
from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
from adaptive_document_agent.document_model.series import metric_identity_key
from adaptive_document_agent.validation.claim_validator import are_observations_compatible


def chart_change_annotation(chart, index, *, scope_text: str = "") -> str:
    """Name a stated endpoint change, otherwise the largest adjacent change.

    The chart was selected semantically by the model. Python only calculates a
    directly comparable difference and retains the exact period endpoints.
    """
    from .composition_data import composition_data, uses_composition_data
    from .pptx_export import _display_scale

    if uses_composition_data(chart):
        if chart.chart_type not in {"stacked_percent", "pie", "doughnut"}:
            return ""
        observations = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
        totals = [index.get(oid) for oid in chart.total_observation_ids if index.get(oid)]
        try:
            mix = composition_data(chart, observations, totals)
        except ValueError:
            return ""
        if len(mix.periods) == 1:
            total = sum(row[0] for row in mix.values)
            if total <= 0:
                return ""
            ranked = sorted(((category, row[0] / total * 100)
                             for category, row in zip(mix.categories, mix.values)),
                            key=lambda part: -part[1])
            if len(ranked) < 2 or abs(ranked[0][1] - ranked[1][1]) < .05:
                return ""
            return f"{mix.periods[0]}: {ranked[0][0]} has the largest share ({ranked[0][1]:,.1f}%)"
        if len(mix.periods) < 2:
            return ""
        first_total = sum(row[0] for row in mix.values)
        last_total = sum(row[-1] for row in mix.values)
        if first_total <= 0 or last_total <= 0:
            return ""
        changes = [(category, row[-1] / last_total * 100 - row[0] / first_total * 100)
                   for category, row in zip(mix.categories, mix.values)]
        category, change = max(changes, key=lambda part: abs(part[1]))
        return f"{category} share, {mix.periods[0]} to {mix.periods[-1]}: {change:+,.1f} pp"
    observations = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
    observations = [item for item in observations if item.value is not None and item.period
                    and item.validation_status == "valid" and item.evidence]
    if len(observations) < 2 or len({metric_identity_key(item) for item in observations}) != 1:
        return ""
    by_period = {}
    for item in observations:
        peers = by_period.setdefault(item.period, [])
        peers.append(item)
    if any(len({(item.value, item.raw_value) for item in peers}) != 1 for peers in by_period.values()):
        return ""
    ordered = sorted((max(peers, key=lambda item: item.confidence) for peers in by_period.values()),
                     key=lambda item: period_sort_key(item.period))
    if len(ordered) < 2 or any(not are_observations_compatible(a, b)[0]
                               for a, b in zip(ordered, ordered[1:])):
        return ""
    start_label = format_observation_period(ordered[0])
    end_label = format_observation_period(ordered[-1])
    stated_range = bool(start_label and end_label and re.search(
        rf"\b(?:from\s+)?{re.escape(start_label)}\s*(?:to|through|until|[-–—])\s*"
        rf"{re.escape(end_label)}\b", scope_text, re.I))
    first, last = ((ordered[0], ordered[-1]) if stated_range else
                   max(zip(ordered, ordered[1:]),
                       key=lambda pair: abs(float(pair[1].value) - float(pair[0].value))))
    semantic = classify_metric(last.metric_original, unit=last.unit,
                               raw_unit=last.raw_unit, value=last.value)
    change = float(last.value) - float(first.value)
    if semantic.is_percentage:
        amount = f"{change:+,.1f} pp"
    else:
        scale, label = _display_scale(ordered, max(abs(float(item.value)) for item in ordered))
        precision = 1 if abs(change / scale) >= 10 else 2
        amount = f"{change / scale:+,.{precision}f}"
        if last.currency:
            amount += f" {last.currency}"
        if label:
            amount += f" {label}"
        elif last.unit == "count" and last.raw_unit not in {None, "", "unknown", "generic"}:
            amount += f" {last.raw_unit}"
        elif last.unit not in {None, "", "currency", "count", "unknown", "generic"}:
            amount += f" {last.unit}"
    return f"{format_observation_period(first)} to {format_observation_period(last)}: {amount}"
