"""One bounded semantic review of evidence left outside the presentation story.

Structural coverage is a retrieval signal, not an importance score. The model
decides whether a missing series changes the interpretation or is redundant.
"""

from __future__ import annotations

import json
from typing import Callable, Literal

from pydantic import BaseModel, Field

from adaptive_document_agent.models import Observation, PipelineResult, PresentationTopicSelection, ValidationIssue
from adaptive_document_agent.models.presentation import PresentationOmission
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMTransportError
from .prompting import load_prompt, untrusted_document_message
from .coverage_representation import representation_links

MAX_REVIEW_CHARACTERS = 120_000
MAX_REVIEW_BATCHES = 8
MAX_REVIEW_CALLS = 3
MAX_REVIEW_OUTPUT_TOKENS = 8192


def _validate_batch(reviewed, current, requested, lookup, primary_pages, validate):
    revised = PresentationTopicSelection(topics=reviewed.topics, omissions=reviewed.omissions)
    validate(revised, lookup, primary_pages=primary_pages)
    previous_ids = {sid for topic in current.topics for sid in topic.series_ids}
    final_ids = {sid for topic in revised.topics for sid in topic.series_ids}
    if final_ids - previous_ids - set(requested):
        raise ValueError('Batch review selected deferred evidence without its complete context.')
    previous = {o.id for sid in previous_ids for o in lookup[sid]}
    selected = [o for sid in final_ids for o in lookup[sid]]
    if not previous <= {o.id for o in selected}:
        raise ValueError('Batch review removed accepted source evidence.')
    local = {d.series_id: d for d in reviewed.coverage_decisions}
    if len(local) != len(reviewed.coverage_decisions) or set(local) != set(requested):
        raise ValueError('Coverage review must decide each requested series exactly once. Missing: '
                         + ', '.join(sorted(set(requested) - set(local))))
    links = {sid: representation_links(lookup[sid], selected) for sid in requested}
    mismatches = [sid for sid, d in local.items() if not d.reason.strip()
                  or (d.decision == 'include') != (links[sid] is not None)]
    if mismatches:
        raise ValueError('Coverage decision must match the evidence actually selected: ' + ', '.join(mismatches))
    return revised, local, {sid: link for sid, link in links.items() if link is not None}


def _review_batch(context, current, requested, lookup, primary_pages, gateway, validate, audit, budget=None):
    """One targeted semantic repair; retain all facts and every rejected attempt."""
    from .coverage_review_context import encode
    budget = budget if budget is not None else {'calls': 0}
    encoded = encode(context)
    messages = [
        {'role': 'system', 'content': load_prompt('presentation_topic_selection.txt') + '\n\n'
         + load_prompt('presentation_topic_coverage_review.txt') + '\n'
         'Retain every current selected source observation. Choose only fully evidenced series in this request. '
         'Deferred catalog entries have no decision yet. Read point_encoding; constants apply to every point. '
         'An include decision needs all facts actually represented, with matching values, periods, units, '
         'definitions, categories and audit status; matching page numbers or measure names is insufficient.'},
        untrusted_document_message(encoded),
    ]
    for attempt in range(2):
        if budget['calls'] >= MAX_REVIEW_CALLS:
            raise ValueError('Coverage model-call budget exhausted; remaining evidence requires review.')
        budget['calls'] += 1
        reviewed = gateway.generate_structured(messages, TopicCoverageReview,
                                               stage='presentation', allow_repair=False,max_tokens=MAX_REVIEW_OUTPUT_TOKENS)
        entry = {'review': reviewed.model_dump(mode='json')}
        audit.setdefault('attempts', []).append(entry)
        audit['review'] = entry['review']
        try:
            revised, decisions, links = _validate_batch(reviewed, current, requested,
                                                       lookup, primary_pages, validate)
            audit['representation_links'] = links
            return revised, decisions
        except ValueError as exc:
            entry['validation_error'] = str(exc)
            if attempt:
                raise
            feedback = {'validation_error': str(exc),
                        'rejected_topics': [t.model_dump(mode='json') for t in reviewed.topics]}
            if len(encoded) + len(encode(feedback)) > MAX_REVIEW_CHARACTERS:
                feedback.pop('rejected_topics')
            if len(encoded) + len(encode(feedback)) > MAX_REVIEW_CHARACTERS:
                raise ValueError('Repair context exceeds the bounded review budget.') from exc
            messages = messages[:2] + [untrusted_document_message(encode(feedback)),
                {'role': 'user', 'content': 'Repair this rejected review using the original full evidence context. '
                 'Return the complete topics and exactly one decision for each requested series. '
                 'If a material series is absent, select it; do not label it included without its facts. '
                 'Explicitly explain omissions. Preserve all previously accepted observations.'}]


class CoverageDecision(BaseModel):
    series_id: str
    decision: Literal["include", "omit"]
    reason: str = Field(min_length=1)


class TopicCoverageReview(PresentationTopicSelection):
    coverage_decisions: list[CoverageDecision] = Field(default_factory=list)


def coverage_review_pending(result: PipelineResult) -> bool:
    """A historical failed review clears only after successful or full coverage."""
    latest = next((issue for issue in reversed(result.validation_warnings)
        if issue.code in {"presentation_topic_coverage_review", "presentation_topic_coverage_unresolved"}), None)
    if latest is None or latest.code != "presentation_topic_coverage_unresolved":
        return False
    from .presentation_topic_selector import series_directory
    _, lookup = series_directory(result)
    selected = {sid for topic in (result.presentation_topics.topics if result.presentation_topics else [])
                for sid in topic.series_ids}
    represented = {item.id for sid in selected if sid in lookup for item in lookup[sid]}
    return any(sid not in lookup or not {item.id for item in lookup[sid]} <= represented
               for sid in latest.related_ids)


def source_period_views(lookup: dict[str, list[Observation]]) -> list[dict]:
    """Link exact source rows across bases without declaring them comparable."""
    from collections import defaultdict
    from adaptive_document_agent.validation.topic_period_consistency import _source_row
    from adaptive_document_agent.services.presentation_period_scope import _period

    rows = defaultdict(list)
    for sid, group in lookup.items():
        key = _source_row(group)
        if key is not None:
            rows[key].append(sid)
    views = []
    for ids in rows.values():
        if len(ids) < 2:
            continue
        entries = []
        for sid in ids:
            periods = {_period(item) for item in lookup[sid]}
            comparable = None not in periods and len(periods) > 1 and len({p[0] for p in periods}) == 1
            entries.append({"series_id": sid,
                "periods": list(dict.fromkeys(item.period for item in lookup[sid])),
                "internally_comparable_periods": comparable})
        views.append({"same_source_row": entries,
            "scope_note": "Separate period views. Never compare different durations or infer missing dates."})
    return views


def review_topic_coverage(
    selection: PresentationTopicSelection,
    result: PipelineResult,
    lookup: dict[str, list[Observation]],
    primary_pages: set[int],
    payload: dict,
    gateway: LLMGateway,
    validate: Callable[..., None],
) -> PresentationTopicSelection:
    """Retain the valid draft if coverage review fails; never select by Python rank."""
    selected_ids = {sid for topic in selection.topics for sid in topic.series_ids}
    represented = {item.id for sid in selected_ids for item in lookup[sid]}
    candidates = [sid for sid, group in lookup.items()
        if not {item.id for item in group} <= represented
        and (not primary_pages or any(e.page in primary_pages for item in group for e in item.evidence))]
    if not candidates:
        return selection

    review_payload = {**payload, "current_selection": selection.model_dump(mode="json"),
        "series_requiring_coverage_decision": candidates,
        "review_scope": "All available series with evidence not represented in the current selected topics."}
    encoded = json.dumps(review_payload, ensure_ascii=False, separators=(",", ":"))
    audit = {"original_selection": selection.model_dump(mode="json"), "candidate_series_ids": candidates}

    def record(code, severity, details):
        result.validation_warnings.append(ValidationIssue(code=code, severity=severity,
            stage="presentation", related_ids=candidates,
            message=json.dumps({**audit, **details}, ensure_ascii=False)))

    if len(encoded) > MAX_REVIEW_CHARACTERS:
        return _review_bounded(selection, candidates, lookup, primary_pages,
                               review_payload, gateway, validate, record)
    reviewed = None
    try:
        reviewed = gateway.generate_structured([
            {"role": "system", "content": load_prompt("presentation_topic_selection.txt") + "\n\n"
             + load_prompt("presentation_topic_coverage_review.txt")},
            untrusted_document_message(encoded),
        ], TopicCoverageReview, stage="presentation", allow_repair=False,max_tokens=MAX_REVIEW_OUTPUT_TOKENS)
        revised = PresentationTopicSelection(topics=reviewed.topics, omissions=reviewed.omissions)
        validate(revised, lookup, primary_pages=primary_pages)
        decisions = {item.series_id: item for item in reviewed.coverage_decisions}
        if len(decisions) != len(reviewed.coverage_decisions) or set(decisions) != set(candidates):
            raise ValueError("Coverage review must decide each requested series exactly once.")
        final_ids = {sid for topic in revised.topics for sid in topic.series_ids}
        final_observations = {item.id for sid in final_ids for item in lookup[sid]}
        for sid, decision in decisions.items():
            included = representation_links(lookup[sid], [o for selected_sid in final_ids for o in lookup[selected_sid]]) is not None
            if not decision.reason.strip() or (decision.decision == "include") != included:
                raise ValueError("Coverage decision must match the evidence actually selected.")
        # A completeness review may regroup topics, but must not silently erase
        # already accepted evidence to make room for a newly selected question.
        removed = selected_ids - final_ids
        explicitly_omitted = {item.series_id for item in revised.omissions}
        if any(not {item.id for item in lookup[sid]} <= final_observations
               and sid not in explicitly_omitted for sid in removed):
            raise ValueError("Previously selected evidence was removed without an explicit omission reason.")
    except (LLMResponseError, LLMTransportError, ValueError) as exc:
        record("presentation_topic_coverage_unresolved", "warning", {
            "reason": str(exc), "rejected_review": reviewed.model_dump(mode="json") if reviewed else None})
        return selection
    # Promote explicit model-authored exclusion reasons to the existing plan
    # coverage notes; the complete decisions remain in the durable audit.
    omitted = {item.series_id for item in revised.omissions}
    for decision in reviewed.coverage_decisions:
        if len(revised.omissions) >= 12:
            break
        if decision.decision == "omit" and decision.series_id not in omitted:
            revised.omissions.append(PresentationOmission(series_id=decision.series_id, reason=decision.reason))
            omitted.add(decision.series_id)
    record("presentation_topic_coverage_review", "info", {"review": reviewed.model_dump(mode="json")})
    return revised


def _review_bounded(selection, candidates, lookup, primary_pages, payload, gateway, validate, record):
    """Review all facts in bounded batches and commit only a complete valid merge."""
    from .coverage_review_context import compact_context, batch_context, encode
    compact = compact_context(payload)
    current = selection.model_copy(deep=True)
    remaining = list(candidates)
    decisions = {}
    batches = []
    budget = {'calls': 0}
    try:
        while remaining:
            represented = {o.id for topic in current.topics for sid in topic.series_ids for o in lookup[sid]}
            # Exact overlapping views are already structurally represented by
            # accepted semantic choices, not chosen by a Python importance rank.
            covered = [sid for sid in remaining if {o.id for o in lookup[sid]} <= represented]
            for sid in covered:
                decisions[sid] = CoverageDecision(series_id=sid, decision='include',
                    reason='All source observations are represented in an accepted model-selected view.')
            remaining = [sid for sid in remaining if sid not in set(covered)]
            if not remaining:
                break
            if len(batches) >= MAX_REVIEW_BATCHES:
                raise ValueError('Complete coverage review exceeds the bounded batch count; no series was silently sampled.')
            batch_budget = int(MAX_REVIEW_CHARACTERS * .88)
            if len(encode(compact)) <= batch_budget and not batches:
                requested = remaining[:]
                context = {**compact, 'current_selection': current.model_dump(mode='json'),
                           'series_requiring_coverage_decision': requested}
            else:
                requested = []
                for sid in remaining:
                    proposal = batch_context(compact, current, [*requested, sid])
                    if len(encode(proposal)) > batch_budget:
                        if not requested and len(encode(proposal)) <= MAX_REVIEW_CHARACTERS:
                            requested.append(sid)  # A complete large series is never split or sampled.
                        break
                    requested.append(sid)
                if not requested:
                    raise ValueError('One complete series and accepted context exceed the bounded review budget; no series was silently sampled.')
                context = batch_context(compact, current, requested)
            encoded = encode(context)
            batch_audit = {'series_ids': requested, 'context_characters': len(encoded)}
            batches.append(batch_audit)
            revised, local = _review_batch(context, current, requested, lookup,
                                           primary_pages, gateway, validate, batch_audit, budget)
            final_ids = {sid for topic in revised.topics for sid in topic.series_ids}
            decisions.update(local)
            # Carry model-authored reasons forward, including earlier batches.
            omitted = {o.series_id for o in revised.omissions}
            for omission in current.omissions:
                if len(revised.omissions) >= 12:
                    break
                if omission.series_id not in final_ids and omission.series_id not in omitted:
                    revised.omissions.append(omission.model_copy(deep=True))
                    omitted.add(omission.series_id)
            current = revised
            remaining = [sid for sid in remaining if sid not in local]
        final_ids = {sid for topic in current.topics for sid in topic.series_ids}
        represented = {o.id for sid in final_ids for o in lookup[sid]}
        for sid, decision in list(decisions.items()):
            if decision.decision == 'omit' and {o.id for o in lookup[sid]} <= represented:
                # A later accepted complete composition can represent an earlier
                # excluded individual view. Keep its semantic decision in the
                # batch audit and reconcile only final structural coverage.
                decisions[sid] = CoverageDecision(series_id=sid, decision='include',
                    reason='Represented by a later model-selected complete view; original review: ' + decision.reason)
        if set(decisions) != set(candidates):
            raise ValueError('Complete coverage review left series without a decision.')
        omitted = {o.series_id for o in current.omissions}
        for decision in decisions.values():
            if len(current.omissions) >= 12:
                break
            if decision.decision == 'omit' and decision.series_id not in omitted:
                current.omissions.append(PresentationOmission(series_id=decision.series_id, reason=decision.reason))
                omitted.add(decision.series_id)
        validate(current, lookup, primary_pages=primary_pages)
    except (LLMResponseError, LLMTransportError, ValueError) as exc:
        record('presentation_topic_coverage_unresolved', 'warning', {
            'reason': str(exc), 'batches': batches, 'unreviewed_series_ids': remaining,
            'context_characters': len(encode(payload)), 'limit': MAX_REVIEW_CHARACTERS})
        return selection
    record('presentation_topic_coverage_review', 'info', {'batches': batches,
        'review': {**current.model_dump(mode='json'),
                   'coverage_decisions': [decisions[sid].model_dump(mode='json') for sid in candidates]}})
    return current
