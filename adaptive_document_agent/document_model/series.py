"""Comparable-series helpers shared by calculation and visualisation layers."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from math import isclose

from adaptive_document_agent.models import Observation
from .period_semantic_validator import extract_period_basis


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
    qualifier_terms = (
        "%", "percent", "percentage", "margin", "rate", "ratio", "share", " per ", " of ",
        "adjusted", "adj.", "non-ifrs", "non ifrs", "non-gaap", "经调整", "非国际",
    )
    if canonical_folded in original_folded or any(term in original_folded for term in qualifier_terms):
        return original
    return canonical


def source_context_key(observation: Observation) -> tuple[str, str]:
    """Retained context is identity evidence, not noise for same-label measures."""
    return tuple(" ".join(str(value or "").split()).casefold() for value in (
        observation.source_section or observation.dimensions.get("section"),
        observation.dimensions.get("table_context"),
    ))


def metric_identity_key(observation: Observation) -> tuple[object, ...]:
    """Identity used to group observations into a single coherent financial series."""
    name = metric_label(observation).casefold()
    u_family = getattr(observation, "unit_family", None) or observation.unit or "generic"
    core_dims = tuple(sorted(observation.category_dimensions.items())) if observation.category_dimensions else tuple(sorted((k, v) for k, v in observation.dimensions.items() if k not in {"table_context", "section", "period_basis"}))
    section = source_context_key(observation)

    # If the metric label is generic (like "Others", "Corporate", "Miscellaneous"),
    # it is strictly contextual to its source table and parent section!
    if is_generic_metric_label(name):
        tbl = observation.effective_table_id or observation.source_table or ""
        return (name, section, tbl, core_dims, u_family, observation.entity, observation.currency, observation.ifrs_status)

    # Non-generic metrics can merge across multi-page tables IF they share same core dimensions,
    # section (if present), and unit family.
    return (name, section, core_dims, u_family, observation.entity, observation.currency, observation.ifrs_status)


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
    # Strip reconciliation and accounting table prefixes: "Add:", "Add -", "Less:", "Less -", etc.
    label = re.sub(r"(?i)^(?:add|less|plus|minus)\s*[:\-\u2013\u2014]\s*", "", label)
    label = re.sub(r"(?i)^(?:adjustments?|reconciliation|sub-?total|total)\s*[:\-\u2013\u2014]\s*", "", label)
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


def sanitize_metric_for_title(name: str, max_length: int = 50) -> str:
    """Sanitize metric label to produce clean, concise text suitable for slide titles."""
    clean = re.sub(r"^[\s\-\u2013\u2014\u2022]+", "", name)
    clean = re.sub(r"(?i)^(?:add|less|plus|minus)\s*[:\-\u2013\u2014]\s*", "", clean)
    clean = re.sub(r"(?i)^(?:adjustments?|reconciliation|sub-?total|total)\s*[:\-\u2013\u2014]\s*", "", clean)
    clean = _TRAILING_UNIT.sub("", clean)
    clean = re.sub(r"\s*\([^)]*(?:note|unaudited|audited|\'000|thousand|million|rmb|usd|hkd)[^)]*\)", "", clean, flags=re.IGNORECASE)
    clean = " ".join(clean.split()).strip(" :;,-")
    if len(clean) > max_length:
        clean = clean[:max_length].rsplit(" ", 1)[0].rstrip(" ,:;-.")
    return clean


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
    return observation.period, observation.entity, tuple(sorted({**observation.dimensions, **observation.category_dimensions}.items())), source_context_key(observation)


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


def canonical_series_partition_key(obs: Observation) -> tuple[object, ...]:
    """Generate canonical partition key for grouping compatible metric observations.

    Criteria:
    - canonical metric: normalized canonical name, falling back to specific display qualifier
    - unit/currency: (is_percentage, unit_family, currency)
    - period basis: 'FY' / '6M' / '3M' / 'YTD' / 'point_in_time' / other duration
    - reporting basis: consolidated vs standalone
    - restatement basis: restated vs original
    - relevant dimensions: core category dimensions (excluding context noise)
    - entity: normalized entity
    """
    if is_generic_metric_label(obs.metric_original) or (obs.metric_canonical and is_generic_metric_label(obs.metric_canonical)):
        m_name = metric_key(obs)
    else:
        m_name = (obs.metric_canonical or metric_label(obs)).strip().casefold()

    u_fam = (getattr(obs, "unit_family", None) or obs.unit or "generic").strip().casefold()
    unit = (obs.unit or obs.raw_unit or "").strip().casefold()
    is_pct = "%" in unit or u_fam == "percentage"
    curr = (obs.currency or "").strip().upper()

    ptype = (getattr(obs, "period_type", None) or "generic").strip().casefold()
    basis = extract_period_basis(obs.period)
    if ptype in {"balance_sheet_date", "point_in_time"} or basis == "point_in_time":
        p_basis = "point_in_time"
    elif ptype == "fiscal_year" and basis == "generic":
        p_basis = "FY"
    else:
        p_basis = basis

    rep_basis = (
        obs.dimensions.get("reporting_basis")
        or obs.dimensions.get("basis")
        or ""
    ).strip().casefold()
    restatement = (
        obs.dimensions.get("restatement")
        or obs.dimensions.get("restated")
        or ""
    ).strip().casefold()

    ifrs = (getattr(obs, "ifrs_status", "") or "UNSPECIFIED").strip().upper()
    if not ifrs or ifrs == "UNSPECIFIED":
        combined = f"{obs.metric_canonical or ''} {obs.metric_original or ''}".casefold()
        ifrs = "ADJUSTED" if any(k in combined for k in ("adjusted", "non-ifrs", "non-gaap", "经调整", "非国际")) else "IFRS"

    if obs.category_dimensions:
        core_dims = tuple(sorted((k, str(v).strip().casefold()) for k, v in obs.category_dimensions.items()))
    else:
        core_dims = tuple(
            sorted(
                (k, str(v).strip().casefold())
                for k, v in obs.dimensions.items()
                if k not in {"table_context", "section", "period_basis", "reporting_basis", "basis", "restatement", "restated", "ifrs_status"}
            )
        )
    entity = (obs.entity or "").strip().casefold()

    return (m_name, ifrs, is_pct, u_fam, curr, p_basis, rep_basis, restatement, core_dims, entity, source_context_key(obs))


def group_comparable_series(
    observations: Iterable[Observation],
    *,
    minimum_periods: int = 2,
) -> list[list[Observation]]:
    """Partition observations into strictly compatible comparable series.

    Guarantees:
    - Never mixes different period bases (FY, 6M, 3M, YTD, point_in_time)
    - Never mixes currencies, percentage types, reporting bases, or restatements
    - Within each group, reconciles presentation-sign duplicates and picks highest confidence
    - Returns lists of observations sorted chronologically by period_sort_key
    """
    groups: dict[tuple[object, ...], list[Observation]] = defaultdict(list)
    for item in observations:
        if item.value is None or not item.period:
            continue
        key = canonical_series_partition_key(item)
        groups[key].append(item)

    results: list[list[Observation]] = []
    for key, items in groups.items():
        by_period: dict[str, list[Observation]] = defaultdict(list)
        for item in items:
            by_period[item.period or ""].append(item)
        if len(by_period) < minimum_periods:
            continue
        series: list[Observation] = []
        has_fatal_conflict = False
        for period_key, period_items in by_period.items():
            if _has_conflict(period_items):
                reconciled, _ = reconcile_observations(period_items)
                if _has_conflict(reconciled):
                    has_fatal_conflict = True
                    break
                period_items = reconciled
            series.append(max(period_items, key=lambda it: (it.confidence, len(it.evidence))))
        if not has_fatal_conflict and len(series) >= minimum_periods:
            results.append(sorted(series, key=lambda item: period_sort_key(item.period)))

    return results


def best_period_series(observations: Iterable[Observation], *, minimum_periods: int = 2) -> list[Observation]:
    """Select one coherent, comparable source series across compatible periods."""
    candidates = group_comparable_series(observations, minimum_periods=minimum_periods)
    if not candidates:
        return []

    # Prioritize FY series if available, then length, confidence, and page evidence
    return max(
        candidates,
        key=lambda series: (
            extract_period_basis(series[0].period) == "FY",
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
    # Matching each pair is insufficient: pooling annual and interim pairs
    # creates a spurious sample. Do not cherry-pick a convenient subset.
    if pairs:
        from adaptive_document_agent.validation.claim_validator import are_observations_compatible
        for left, right in pairs[1:]:
            # Paired samples may represent different regions/respondents/indexes;
            # their dimensions already match within each pair above.
            if not are_observations_compatible(pairs[0][0], left, allow_sample_dimensions=True)[0] or not are_observations_compatible(pairs[0][1], right, allow_sample_dimensions=True)[0]:
                return []
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
