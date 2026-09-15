"""Comparable-series helpers shared by calculation and visualisation layers."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from math import isclose

from adaptive_document_agent.models import Observation


def metric_label(observation: Observation) -> str:
    """Return the most specific trustworthy display name for a metric.

    Semantic resolution may map a qualified source label such as
    ``Revenue: % of Revenue`` to the broader canonical name ``Revenue``.
    Keeping the source qualifier prevents amounts, margins, shares, and
    per-unit values from collapsing into one analytical series.
    """
    original = " ".join(observation.metric_original.split()).strip()
    canonical = " ".join((observation.metric_canonical or "").split()).strip()
    if not canonical:
        return original
    original_folded = original.casefold()
    canonical_folded = canonical.casefold()
    if original_folded == canonical_folded:
        return canonical
    qualifier_terms = ("%", "percent", "percentage", "margin", "rate", "ratio", "share", " per ", " of ")
    if canonical_folded in original_folded or any(term in original_folded for term in qualifier_terms):
        return original
    return canonical


def metric_key(observation: Observation) -> str:
    return metric_label(observation).casefold()


def context_key(observation: Observation) -> tuple[object, ...]:
    """Identity used to align observations without assuming a document type."""
    return observation.period, observation.entity, tuple(sorted(observation.dimensions.items()))


def conflicting_groups(observations: Iterable[Observation]) -> list[list[Observation]]:
    """Return same-context observations whose normalised values disagree."""
    groups: dict[tuple[object, ...], list[Observation]] = defaultdict(list)
    for item in observations:
        groups[(metric_key(item), context_key(item), item.unit, item.currency)].append(item)
    return [items for items in groups.values() if _has_conflict(items)]


def presentation_sign_variant_groups(observations: Iterable[Observation]) -> list[list[Observation]]:
    """Return groups that differ only by source-table presentation sign.

    These observations remain distinct in the fact base.  The classification
    merely prevents a common expense/loss display convention from being
    reported as an unexplained numeric contradiction.
    """
    groups: dict[tuple[object, ...], list[Observation]] = defaultdict(list)
    for item in observations:
        groups[(metric_key(item), context_key(item), item.unit, item.currency)].append(item)
    return [items for items in groups.values() if _is_presentation_sign_variant(items)]


def best_period_series(observations: Iterable[Observation], *, minimum_periods: int = 2) -> list[Observation]:
    """Select one coherent, comparable source series without mixing tables."""
    groups: dict[tuple[object, ...], list[Observation]] = defaultdict(list)
    for item in observations:
        if item.value is None or not item.period:
            continue
        groups[
            (
                item.entity,
                tuple(sorted(item.dimensions.items())),
                item.unit,
                item.currency,
                _primary_table_id(item),
            )
        ].append(item)

    candidates: list[list[Observation]] = []
    for values in groups.values():
        by_period: dict[str, list[Observation]] = defaultdict(list)
        for item in values:
            by_period[item.period or ""].append(item)
        if len(by_period) < minimum_periods or any(_has_conflict(items) for items in by_period.values()):
            continue
        series = [max(items, key=lambda item: item.confidence) for items in by_period.values()]
        candidates.append(sorted(series, key=lambda item: period_sort_key(item.period)))
    if not candidates:
        return []
    return max(
        candidates,
        key=lambda series: (
            len(series),
            sum(item.confidence for item in series) / len(series),
            len({source.page for item in series for source in item.evidence}),
            str((series[0].entity, sorted(series[0].dimensions.items()), _primary_table_id(series[0]))),
        ),
    )


def reconcile_observations(observations: Iterable[Observation]) -> tuple[list[Observation], bool]:
    """Choose a coherent source when a task contains sign-only duplicates."""
    values = list(observations)
    sign_groups = presentation_sign_variant_groups(values)
    if not sign_groups:
        return values, False
    excluded: set[str] = set()
    for group in sign_groups:
        by_source: dict[str | None, list[Observation]] = defaultdict(list)
        for item in group:
            by_source[_primary_table_id(item)].append(item)
        selected_source = max(
            by_source,
            key=lambda source: (
                len(by_source[source]),
                sum(item.confidence for item in by_source[source]) / len(by_source[source]),
                source or "",
            ),
        )
        excluded.update(item.id for source, items in by_source.items() if source != selected_source for item in items)
    return [item for item in values if item.id not in excluded], bool(excluded)


def paired_observations(
    observations: Iterable[Observation],
    left_metric: str,
    right_metric: str,
) -> list[tuple[Observation, Observation]]:
    """Pair two metrics only where period, entity, and dimensions all match."""
    grouped: dict[str, dict[tuple[object, ...], list[Observation]]] = defaultdict(lambda: defaultdict(list))
    for item in observations:
        if item.value is not None:
            grouped[metric_key(item)][context_key(item)].append(item)
    left_name, right_name = left_metric.casefold(), right_metric.casefold()
    common = set(grouped[left_name]) & set(grouped[right_name])
    pairs: list[tuple[Observation, Observation]] = []
    for key in sorted(common, key=_context_sort_key):
        left_values = grouped[left_name][key]
        right_values = grouped[right_name][key]
        if _has_conflict(left_values) or _has_conflict(right_values):
            continue
        pairs.append((max(left_values, key=lambda item: item.confidence), max(right_values, key=lambda item: item.confidence)))
    return pairs


def period_sort_key(value: str | None) -> tuple[int, int, str]:
    """Sort common period labels while keeping unfamiliar labels deterministic."""
    text = value or ""
    year_match = re.search(r"(?:19|20)\d{2}", text)
    year = int(year_match.group()) if year_match else 10**9
    basis = 0 if text.upper().startswith("FY") else 1
    return year, basis, text.casefold()


def _has_conflict(items: list[Observation]) -> bool:
    numeric = [float(item.value) for item in items if item.value is not None]
    if len(numeric) < 2 or all(isclose(numeric[0], value, rel_tol=1e-9, abs_tol=1e-9) for value in numeric[1:]):
        return False
    return not _is_presentation_sign_variant(items)


def _is_presentation_sign_variant(items: list[Observation]) -> bool:
    numeric = [float(item.value) for item in items if item.value is not None]
    if len(numeric) < 2 or not (any(value < 0 for value in numeric) and any(value >= 0 for value in numeric)):
        return False
    magnitude = abs(numeric[0])
    if not all(isclose(magnitude, abs(value), rel_tol=1e-9, abs_tol=1e-9) for value in numeric[1:]):
        return False
    # Require source-level evidence that this is a display-sign difference,
    # rather than silently treating arbitrary opposite values as equivalent.
    raw_negative = [item.raw_value.strip().startswith("(") or item.raw_value.strip().startswith("-") for item in items]
    return any(raw_negative) and not all(raw_negative)


def _primary_table_id(item: Observation) -> str | None:
    return next((source.table_id for source in item.evidence if source.table_id), None)


def _context_sort_key(key: tuple[object, ...]) -> tuple[object, ...]:
    period = key[0] if isinstance(key[0], str) else None
    return (*period_sort_key(period), str(key[1:]))
