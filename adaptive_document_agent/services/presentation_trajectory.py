"""Source-aligned display copy for analytical questions and reversals."""

from __future__ import annotations

import re

from adaptive_document_agent.document_model import period_sort_key


_DIRECTION = re.compile(r"\b(?:increase|increased|rise|rose|grow|grew|growth|"
                        r"decrease|decreased|fall|fell|decline|declined|"
                        r"widen|widened|contract|contracted)\b", re.I)
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


def supported_subtitle(slide, charts, index):
    """Answer a planned question or qualify an overbroad directional claim.

    The model has already chosen the subject and charts. This layer uses their
    same validated series for a compact, literal caption when a question lacks
    an answer or a direction sentence hides an interior reversal.
    """
    from .executive_brief import _brief_fact_for_chart

    message = slide.message.strip()
    if not message or not charts:
        return message
    question = message.endswith('?')
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
        if fact is None or len(fact[0]) > 155:
            continue
        metric = ordered[0].metric_original.casefold()
        metric_tokens = set(re.findall(r"[A-Za-z]+", metric)) - _STOP
        score = len(query_tokens & metric_tokens)
        if question and _RATIO.search(claims) and (
                _RATIO.search(metric) or ordered[0].unit in {'percent', '%'}):
            score += 3
        candidates.append((score, fact[0]))
    if not candidates:
        return message
    return max(candidates, key=lambda candidate: candidate[0])[1]
