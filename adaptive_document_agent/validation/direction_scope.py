"""Bind temporal direction words to observed periods without inventing a pivot."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from adaptive_document_agent.models import Observation
from adaptive_document_agent.document_model.period_semantic_validator import extract_period_basis


DirectionSpan = tuple[str, str, int, int]
_SEQUENCE = re.compile(r"\b(?:then|before|prior to|subsequently)\b", re.I)
_YEAR = r"(?:19|20)\d{2}"
_PERIOD = rf"(?:{_YEAR}-\d{{2}}-\d{{2}}|(?:FY\s*|[1369]M\s*|[12]H\s*|Q[1-4]\s*)?{_YEAR})"
_RANGE = re.compile(
    rf"\b(?:from\s+|between\s+)?(?P<start>{_PERIOD})\s*"
    rf"(?:to|through|until|and|[–-])\s*(?P<end>{_PERIOD})\b", re.I,
)


@dataclass(frozen=True)
class DirectionScope:
    observations: list[Observation] | None = None
    error: str = ""


def _sequence_between(clause: str, start: int, end: int, metric_spans: list[tuple[int, int]]):
    return next((m for m in _SEQUENCE.finditer(clause, start, end)
                 if not any(a <= m.start() and m.end() <= b for a, b in metric_spans)), None)


def has_temporal_sequence(clause: str, associations: list[DirectionSpan], metric: str,
                          metric_spans: list[tuple[int, int]]) -> bool:
    return any(a[0] == b[0] == metric and _sequence_between(clause, a[3], b[2], metric_spans)
               for a, b in zip(associations, associations[1:]))


def _period_index(label: str, observations: list[Observation]) -> int | None:
    normalized = re.sub(r"\s+", "", label).casefold()
    matches = []
    for index, obs in enumerate(observations):
        period = re.sub(r"\s+", "", obs.period or "").casefold()
        # A bare year can identify an annual observation, never an interim one.
        if period == normalized or period.removeprefix("fy") == normalized.removeprefix("fy"):
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def predicate_conjunctions(clause: str):
    """Exclude the conjunction inside an explicit 'between X and Y' range."""
    return [m for m in re.finditer(r"\band\b", clause, re.I)
            if not (re.search(rf"\bbetween\s+{_PERIOD}\s*$", clause[:m.start()], re.I)
                    and re.match(rf"\s*{_PERIOD}\b", clause[m.end():], re.I))]


def _separator_bounds(clause: str, left_end: int, right_start: int,
                      metric_spans: list[tuple[int, int]]) -> tuple[int, int] | None:
    # Independent conjuncts own their prefix periods as well as their verbs.
    conjunctions = [m for m in predicate_conjunctions(clause)
                    if left_end <= m.start() and m.end() <= right_start]
    if conjunctions:
        return conjunctions[-1].span()
    temporal = _sequence_between(clause, left_end, right_start, metric_spans)
    if temporal:
        return temporal.span()
    return None


def _group_bounds(clause: str, associations: list[DirectionSpan], position: int,
                  metric_spans: list[tuple[int, int]]) -> tuple[int, int]:
    metric = associations[position][0]
    lo = hi = position
    while lo > 0:
        previous, current = associations[lo - 1], associations[lo]
        if previous[0] != metric or not _sequence_between(clause, previous[3], current[2], metric_spans):
            break
        lo -= 1
    while hi + 1 < len(associations):
        current, following = associations[hi], associations[hi + 1]
        if following[0] != metric or not _sequence_between(clause, current[3], following[2], metric_spans):
            break
        hi += 1
    return lo, hi


def _context_bounds(clause: str, associations: list[DirectionSpan], lo: int, hi: int,
                    metric_spans: list[tuple[int, int]]) -> tuple[int, int]:
    start, end = 0, len(clause)
    if lo > 0:
        separator = _separator_bounds(clause, associations[lo - 1][3], associations[lo][2], metric_spans)
        start = separator[1] if separator else associations[lo][2]
    if hi + 1 < len(associations):
        separator = _separator_bounds(clause, associations[hi][3], associations[hi + 1][2], metric_spans)
        end = separator[0] if separator else associations[hi + 1][2]
    return start, end


def direction_context(clause: str, associations: list[DirectionSpan], direction: DirectionSpan,
                      metric_spans: list[tuple[int, int]]) -> str:
    """Series selection may only use this predicate/group's period qualifiers."""
    lo, hi = _group_bounds(clause, associations, associations.index(direction), metric_spans)
    start, end = _context_bounds(clause, associations, lo, hi, metric_spans)
    return clause[start:end]


def resolve_direction_scope(
    clause: str,
    associations: list[DirectionSpan],
    direction: DirectionSpan,
    observations: list[Observation],
    trend: Callable[[Observation, Observation], object],
    *,
    allow_other_period_bases: bool = False,
    metric_spans: list[tuple[int, int]] | None = None,
) -> DirectionScope:
    """Resolve explicit bounds or an unambiguous ordered sequence.

    Three points and two predicates identify two adjacent comparisons. Longer
    series require either explicit bounds or one unique run per predicate.
    An unresolved temporal claim must not fall back to whole-series endpoints.
    """
    position = associations.index(direction)
    metric, _, start, end = direction
    metric_spans = metric_spans or []
    # Locate temporal groups without crossing another metric's predicate.
    lo, hi = _group_bounds(clause, associations, position, metric_spans)
    local_start, local_end = _context_bounds(clause, associations, position, position, metric_spans)
    local_text = clause[local_start:local_end]
    ranges = list(_RANGE.finditer(local_text))
    if len(ranges) > 1 and allow_other_period_bases:
        basis = extract_period_basis(observations[0].period)
        ranges = [r for r in ranges if extract_period_basis(r['start']) == basis
                  and extract_period_basis(r['end']) == basis]
    if ranges:
        if len(ranges) != 1:
            return DirectionScope(error="Several period ranges qualify the same direction word")
        match = ranges[0]
        first = _period_index(match['start'], observations)
        last = _period_index(match['end'], observations)
        if first is None or last is None or first >= last:
            return DirectionScope(error="The stated period range is missing or not chronological")
        return DirectionScope(observations[first:last + 1])

    period_mentions = list(re.finditer(rf"\b{_PERIOD}\b", local_text, re.I))
    if period_mentions:
        if (lo == hi and len(observations) == 2 and len(period_mentions) == 1
                and _period_index(period_mentions[0].group(), observations) == 1):
            # With only two linked observations the named final period has
            # exactly one supported comparison, unlike a multi-year series.
            return DirectionScope(observations)
        return DirectionScope(error="The temporal direction needs explicit start and end periods")
    if lo == hi:
        # An explicit temporal connector with an unbound predicate is unsafe.
        if _sequence_between(clause, end, local_end, metric_spans):
            return DirectionScope(error="The temporal predicates do not have one bound metric")
        return DirectionScope()
    count = hi - lo + 1
    if len(observations) == count + 1:
        index = position - lo
        return DirectionScope(observations[index:index + 2])
    # Consecutive identical semantic trends form a single run. Do not select a
    # subset of runs or collapse an extra reversal to make the sentence fit.
    runs: list[tuple[int, int, object]] = []
    for index, (first, last) in enumerate(zip(observations, observations[1:])):
        state = trend(first, last)
        if runs and runs[-1][2] == state:
            runs[-1] = (runs[-1][0], index + 1, state)
        else:
            runs.append((index, index + 1, state))
    if len(runs) == count:
        first, last, _ = runs[position - lo]
        return DirectionScope(observations[first:last + 1])
    return DirectionScope(error="The number of temporal predicates does not identify unique observed segments")
