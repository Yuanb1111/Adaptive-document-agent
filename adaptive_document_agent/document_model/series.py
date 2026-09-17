"""Comparable-series helpers shared by calculation and visualisation layers."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from math import isclose

from adaptive_document_agent.models import Observation


_METRIC_NOISE_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "m", "of", "on", "or", "the", "to", "with",
}
_TRAILING_UNIT = re.compile(
    r"\s*:\s*(?:rmb|cny|usd|hkd|eur|gbp)(?:\s*[\u2018\u2019']*\s*0{3}|\s+in\s+(?:thousands|millions|billions))?\s*$",
    flags=re.IGNORECASE,
)


_GENERIC_METRIC_PATTERNS = (
    r"^others?$",
    r"^other\s+(?:income|expenses?|costs?|revenue|assets?|liabilities|payables?|receivables?|segment|business)$",
    r"^corporate(?:/unallocated)?$",
    r"^unallocated$",
    r"^miscellaneous$",
    r"^rest\s+of\s+(?:the\s+)?world$",
    r"^others?\s+segment$",
    r"^all\s+others?$",
    r"^其[他它]$",
    r"^其[他它](?:收入|支出|费用|成本|业务)$",
    r"^未分配$",
    r"^未分摊$",
)


def is_generic_metric_label(label: str) -> bool:
    clean = " ".join(label.strip().split()).casefold()
    return any(bool(re.search(pat, clean)) for pat in _GENERIC_METRIC_PATTERNS)


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


def metric_identity_key(observation: Observation) -> tuple[object, ...]:
    """Identity used to group observations into a single coherent financial series."""
    name = metric_label(observation).casefold()
    u_family = getattr(observation, "unit_family", None) or observation.unit or "generic"
    core_dims = tuple(sorted(observation.category_dimensions.items())) if observation.category_dimensions else tuple(sorted((k, v) for k, v in observation.dimensions.items() if k not in {"table_context", "section", "period_basis"}))
    section = (observation.source_section or "").casefold()

    # If the metric label is generic (like "Others", "Corporate", "Miscellaneous"),
    # it is strictly contextual to its source table and parent section!
    if is_generic_metric_label(name):
        tbl = observation.effective_table_id or observation.source_table or ""
        return (name, section, tbl, core_dims, u_family, observation.entity)

    # Non-generic metrics can merge across multi-page tables IF they share same core dimensions,
    # section (if present), and unit family.
    return (name, section, core_dims, u_family, observation.entity)


def metric_key(observation: Observation) -> str:
    name = metric_label(observation)
    if is_generic_metric_label(name):
        sec = observation.source_section
        tbl = observation.source_table
        context_part = sec or tbl
        if context_part:
            return f"{context_part}: {name}".casefold()
    return name.casefold()


def display_metric_name(observation: Observation) -> str:
    """Return a clean presentation label without changing the retained source value."""
    label = metric_label(observation)
    label = re.sub(r"^[\s\-\u2013\u2014\u2022]+", "", label)
    label = _TRAILING_UNIT.sub("", label)
    label = " ".join(label.split()).strip(" :;,-")

    if is_generic_metric_label(label):
        sec = observation.source_section
        if sec and sec.casefold() not in label.casefold():
            label = f"{sec}: {label}"

    # A leading dash commonly marks a child row. Restore a short, usable
    # parent label only when the source explicitly retained one.
    if observation.metric_original.lstrip().startswith(("-", "\u2013", "\u2014", "\u2022")):
        context = " ".join(observation.dimensions.get("table_context", "").split()).strip(" :;,-")
        if context and len(context) <= 48 and is_meaningful_metric_name(context) and context.casefold() not in label.casefold():
            label = f"{context}: {label}"
    return label


def is_meaningful_metric_name(value: str) -> bool:
    """Reject fragments and table grammar that cannot identify a metric."""
    clean = _TRAILING_UNIT.sub("", " ".join(value.split())).strip(" :;,-")
    if len(clean) < 2 or not re.search(r"[A-Za-z\u00c0-\u024f\u3400-\u9fff]", clean):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}(?:[-/.]\d{1,2}){0,2}", clean):
        return False
    tokens = re.findall(r"[A-Za-z]+", clean.casefold())
    if tokens and all(token in _METRIC_NOISE_WORDS for token in tokens):
        return False
    if len(tokens) == 1 and len(tokens[0]) == 1:
        return False
    return True


def is_meaningful_metric(observation: Observation) -> bool:
    """Return whether an observation has a complete, displayable metric name."""
    return is_meaningful_metric_name(display_metric_name(observation))


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
    """Return groups that differ only by source-table presentation sign."""
    groups: dict[tuple[object, ...], list[Observation]] = defaultdict(list)
    for item in observations:
        groups[(metric_key(item), context_key(item), item.unit, item.currency)].append(item)
    return [items for items in groups.values() if _is_presentation_sign_variant(items)]


def best_period_series(observations: Iterable[Observation], *, minimum_periods: int = 2) -> list[Observation]:
    """Select one coherent, comparable source series across compatible periods."""
    groups: dict[tuple[object, ...], list[Observation]] = defaultdict(list)
    for item in observations:
        if item.value is None or not item.period:
            continue
        ident = metric_identity_key(item)
        p_type = getattr(item, "period_type", "fiscal_year")
        groups[(ident, p_type, item.currency)].append(item)

    candidates: list[list[Observation]] = []
    for values in groups.values():
        by_period: dict[str, list[Observation]] = defaultdict(list)
        for item in values:
            by_period[item.period or ""].append(item)
        if len(by_period) < minimum_periods:
            continue
        series: list[Observation] = []
        has_fatal_conflict = False
        for period_key, items in by_period.items():
            if _has_conflict(items):
                reconciled, _ = reconcile_observations(items)
                if _has_conflict(reconciled):
                    has_fatal_conflict = True
                    break
                items = reconciled
            series.append(max(items, key=lambda it: (it.confidence, len(it.evidence))))
        if not has_fatal_conflict and len(series) >= minimum_periods:
            candidates.append(sorted(series, key=lambda item: period_sort_key(item.period)))

    if not candidates:
        return []

    return max(
        candidates,
        key=lambda series: (
            len(series),
            sum(item.confidence for item in series) / len(series),
            len({source.page for item in series for source in item.evidence}),
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
