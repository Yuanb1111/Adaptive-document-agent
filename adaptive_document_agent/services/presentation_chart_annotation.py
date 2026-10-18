"""Small, calculated chart captions for model-selected comparable series."""

from __future__ import annotations

import re

from adaptive_document_agent.document_model import period_sort_key
from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
from adaptive_document_agent.document_model.series import metric_identity_key
from adaptive_document_agent.validation.claim_validator import are_observations_compatible


def _stated_period_pair(ordered, scope_text: str) -> tuple[bool, tuple[int, int] | None]:
    """Resolve literal endpoint labels, without choosing among competing ranges.

    Period-shaped labels also detect unsupported endpoints so an explicit range
    cannot silently become an unrelated latest-period comparison.
    """
    aliases: dict[str, set[int]] = {}
    for position, item in enumerate(ordered):
        for label in (format_observation_period(item), item.period, item.as_of_date):
            if label:
                key = " ".join(label.rstrip("*").split()).casefold()
                aliases.setdefault(key, set()).add(position)
    if not scope_text or not aliases:
        return False, None
    literal_labels = [re.escape(label).replace(r"\ ", r"\s+")
                      for label in sorted(aliases, key=len, reverse=True)]
    period_shapes = [r"\d{4}[-/.]\d{2}[-/.]\d{2}",
                     r"\d{1,2}\s+[a-z]{3,9}\s+\d{4}",
                     r"[a-z]{3,9}\s+\d{1,2},?\s+\d{4}",
                     r"(?:FY|[1-9]M|1[0-2]M|Q[1-4]|[12]H)\s*\d{4}",
                     r"\d{4}"]
    token = "(?:" + "|".join([*literal_labels, *period_shapes]) + ")"
    pattern = re.compile(rf"(?<!\w)(?P<start>{token})\*?\s*"
                         rf"(?:to|through|until|[-–—])\s*(?P<end>{token})\*?"
                         rf"(?!\w|[-/.]\d{{2}}(?!\d))", re.I)
    matches, position = [], 0
    while match := pattern.search(scope_text, position):
        matches.append(match)
        # Retain overlapping pairs in A to B to C, but never reparse the year
        # suffix of an already consumed date label as a separate endpoint.
        position = match.end("start")
    pairs = set()
    for match in matches:
        start, end = (aliases.get(" ".join(match.group(name).split()).casefold(), set())
                      for name in ("start", "end"))
        if len(start) != 1 or len(end) != 1:
            return True, None
        pair = (next(iter(start)), next(iter(end)))
        if pair[0] >= pair[1]:
            return True, None
        pairs.add(pair)
    return bool(matches), next(iter(pairs)) if len(pairs) == 1 else None


def chart_change_annotation(chart, index, *, scope_text: str = "") -> str:
    """Name a stated endpoint change, otherwise the latest comparable change.

    The chart was selected semantically by the model. Python only calculates a
    directly comparable difference and retains the exact period endpoints.
    """
    from .composition_data import composition_data, uses_composition_data
    from .pptx_export import _display_scale, _unit_label

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
        representatives = [next(item for item in observations if item.period == period)
                           for period in mix.periods]
        has_range, stated_pair = _stated_period_pair(representatives, scope_text)
        if has_range and stated_pair is None:
            return ""
        start, end = stated_pair if stated_pair is not None else (0, len(mix.periods) - 1)
        first_total = sum(row[start] for row in mix.values)
        last_total = sum(row[end] for row in mix.values)
        if first_total <= 0 or last_total <= 0:
            return ""
        changes = [(category, row[end] / last_total * 100 - row[start] / first_total * 100)
                   for category, row in zip(mix.categories, mix.values)]
        category, change = max(changes, key=lambda part: abs(part[1]))
        return f"{category} share, {mix.periods[start]} to {mix.periods[end]}: {change:+,.1f} pp"
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
    has_range, stated_pair = _stated_period_pair(ordered, scope_text)
    if has_range and stated_pair is None:
        return ""
    start, end = stated_pair if stated_pair is not None else (len(ordered) - 2, len(ordered) - 1)
    first, last = ordered[start], ordered[end]
    semantic = classify_metric(last.metric_original, unit=last.unit,
                               raw_unit=last.raw_unit, value=last.value)
    change = float(last.value) - float(first.value)
    if semantic.is_percentage:
        amount = f"{change:+,.1f} pp"
    else:
        scale, label = _display_scale(ordered, max(abs(float(item.value)) for item in ordered))
        precision = (0 if last.unit in {'count', 'units'} and change / scale == int(change / scale)
                     else 1 if abs(change / scale) >= 10 else 2)
        amount = f"{change / scale:+,.{precision}f}"
        if last.currency:
            # Use the same source-bound unit as the chart axis, including a
            # price/rate denominator. A delta has the unit of its operands.
            amount += f" {_unit_label(ordered, label)}"
        elif label:
            amount += f" {label}"
        elif last.unit == "count" and last.raw_unit not in {None, "", "unknown", "generic"}:
            amount += f" {last.raw_unit}"
        elif last.unit == "count":
            amount += f" {_unit_label(ordered, label)}"
        elif last.unit not in {None, "", "currency", "count", "unknown", "generic"}:
            amount += f" {last.unit}"
    return f"{format_observation_period(first)} to {format_observation_period(last)}: {amount}"
