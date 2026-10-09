"""Source-aligned display copy for analytical questions and reversals."""

from __future__ import annotations

import re

from adaptive_document_agent.document_model import period_sort_key


_DIRECTION = re.compile(r"\b(?:increas\w*|ris\w*|rose|grow\w*|grew|"
                        r"decreas\w*|fall\w*|fell|declin\w*|"
                        r"widen\w*|contract\w*|narrow\w*|lower|higher)\b", re.I)
_REVERSAL = re.compile(r"\b(?:peak|trough|rebound|recover|fluctuat|revers|"
                       r"then|before|partially)\w*\b", re.I)
_RATIO = re.compile(r"\b(?:ratio|share|percent|percentage|intensity|"
                    r"relative|rate|margin|proportion)\b|%", re.I)
_STOP = {"the", "and", "over", "under", "reported", "values", "years", "periods",
         "how", "has", "have", "did", "does", "what", "with", "from", "into", "total"}


def _series(chart, index):
    """Return one distinct numeric value per ordered period for a simple chart."""
    from .composition_data import uses_composition_data
    from .pptx_export import _chart_findings

    if uses_composition_data(chart) or not _chart_findings([chart], index):
        return []
    by_period = {}
    for identifier in chart.observation_ids:
        item = index.get(identifier)
        if item and item.period and item.value is not None:
            previous = by_period.get(item.period)
            if previous is None or item.confidence > previous.confidence:
                by_period[item.period] = item
    return sorted(by_period.values(), key=lambda item: period_sort_key(item.period))


def _has_turn(ordered):
    values = [float(item.value) for item in ordered]
    return any((values[i]-values[i-1]) * (values[i+1]-values[i]) < 0
               for i in range(1, len(values)-1))


def scoped_direction_title(title, charts, index):
    """Add the exact plotted endpoint period to a model-written directional title.

    A shared scope is required when several charts appear together. This only
    qualifies the model's claim; it never derives a direction from the numbers.
    """
    from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
    from adaptive_document_agent.document_model.series import metric_identity_key
    from adaptive_document_agent.validation.claim_validator import are_observations_compatible

    if not _DIRECTION.search(title) or not charts:
        return title
    scopes = set()
    for chart in charts:
        plotted = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
        if len({metric_identity_key(item) for item in plotted}) != 1:
            return title
        ordered = _series(chart, index)
        if len(ordered) < 2 or not are_observations_compatible(ordered[0], ordered[-1])[0]:
            return title
        first, last = format_observation_period(ordered[0]), format_observation_period(ordered[-1])
        if not first or not last or first == last:
            return title
        scopes.add((first, last))
    if len(scopes) != 1:
        return title
    first, last = next(iter(scopes))
    if first in title and last in title:
        return title
    return f"{title} ({first}–{last})"


def supported_subtitle(slide, charts, index, *, denominators=None):
    """Answer a planned question or qualify an overbroad directional claim.

    The model has already chosen the subject and charts. This layer uses their
    same validated series for a compact, literal caption when a question lacks
    an answer or a direction sentence hides an interior reversal.
    """
    from .executive_brief import _brief_fact_for_chart

    message = slide.message.strip()
    if not message or not charts:
        return message
    question = '?' in message and bool(re.match(r"(?i)^(?:how|what|which|did|does|has|have)\b", message))
    claims = f'{slide.title} {message}'
    if not question and (not _DIRECTION.search(claims) or _REVERSAL.search(claims)):
        return message
    candidates = []
    query_tokens = {token for token in re.findall(r"[A-Za-z]+", claims.casefold())
                    if len(token) > 2 and token not in _STOP}
    for chart in charts:
        ordered = _series(chart, index)
        if len(ordered) < 2 or (not question and not _has_turn(ordered)):
            continue
        fact = _brief_fact_for_chart(chart, index)
        if fact is None or len(fact[0]) > 300:
            continue
        metric = ordered[0].metric_original.casefold()
        metric_tokens = set(re.findall(r"[A-Za-z]+", metric)) - _STOP
        score = len(query_tokens & metric_tokens)
        if question and _RATIO.search(claims) and (
                _RATIO.search(metric) or ordered[0].unit in {'percent', '%'}):
            score += 3
        from .presentation_labels import qualified_metric_name, source_share_heading
        label = qualified_metric_name(ordered[0])
        scoped = source_share_heading(label, ordered, denominators or {})
        caption = scoped + fact[0][len(label):] if fact[0].startswith(label + ':') else fact[0]
        candidates.append((score, caption))
    if not candidates:
        return message
    answer = max(candidates, key=lambda candidate: candidate[0])[1]
    # A source definition after the question must remain visible too.
    suffix = message.split('?', 1)[1].strip() if question else ''
    return ' '.join(part for part in (answer, suffix) if part)
