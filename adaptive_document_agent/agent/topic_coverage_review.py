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

MAX_REVIEW_CHARACTERS = 120_000


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
        record("presentation_topic_coverage_unresolved", "warning", {
            "reason": "Complete coverage context exceeds the bounded review budget; no series was silently sampled.",
            "context_characters": len(encoded), "limit": MAX_REVIEW_CHARACTERS})
        return selection
    reviewed = None
    try:
        reviewed = gateway.generate_structured([
            {"role": "system", "content": load_prompt("presentation_topic_selection.txt") + "\n\n"
             + load_prompt("presentation_topic_coverage_review.txt")},
            untrusted_document_message(encoded),
        ], TopicCoverageReview, stage="presentation", allow_repair=False)
        revised = PresentationTopicSelection(topics=reviewed.topics, omissions=reviewed.omissions)
        validate(revised, lookup, primary_pages=primary_pages)
        decisions = {item.series_id: item for item in reviewed.coverage_decisions}
        if len(decisions) != len(reviewed.coverage_decisions) or set(decisions) != set(candidates):
            raise ValueError("Coverage review must decide each requested series exactly once.")
        final_ids = {sid for topic in revised.topics for sid in topic.series_ids}
        final_observations = {item.id for sid in final_ids for item in lookup[sid]}
        for sid, decision in decisions.items():
            included = {item.id for item in lookup[sid]} <= final_observations
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
