"""Retain selected questions when a takeaway cannot bind to unique evidence."""

import json

from adaptive_document_agent.models import PipelineResult, PresentationPlan, ValidationIssue
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan
from adaptive_document_agent.validation.presentation_provenance import insight_inputs

_WITHHELD_PREFIX = "[claim_scope_withheld] "


def withheld_topic_ids(plan: PresentationPlan) -> set[str]:
    """Read durable audit markers so later summary rebuilds cannot revive a claim."""
    identifiers = set()
    for note in plan.editorial_notes:
        if not note.startswith(_WITHHELD_PREFIX):
            continue
        try:
            entry = json.loads(note[len(_WITHHELD_PREFIX):])
        except (TypeError, ValueError):
            continue
        if isinstance(entry, dict) and isinstance(entry.get("topic_id"), str):
            identifiers.add(entry["topic_id"])
    return identifiers


def recover_cached_topic_claims(plan: PresentationPlan, result: PipelineResult) -> list[str]:
    """Apply the compiler's ambiguity boundary to an already retained topic plan.

    Source-bound share preparation can legitimately restore cached wording,
    but that copy still needs the strict metric/category scope checks. Only
    the retained plan is eligible; in-progress compilation keeps its existing
    explicit validation boundary. Contradictions and other errors stay blocked.
    """
    if (plan is not result.presentation_plan or not result.presentation_topics
            or plan.planning_origin not in {"topic_compilation", "topic_recovery"}):
        return []
    issues = ClaimValidator().validate_plan(plan, result.observations, result.charts,
                                           insight_observation_ids=insight_inputs(result))
    if not any(issue.code == "direction_scope_ambiguous" for issue in issues):
        return []
    return recover_unscoped_topic_claims(plan, result, issues)


def validate_selected_topic_claims(plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
    """Use one strict claim-recovery boundary for compiled and fallback topics."""
    refs = insight_inputs(result)
    plan, repairs = repair_presentation_plan(plan, result.observations, result.charts,
                                            insight_observation_ids=refs)
    validator = ClaimValidator()
    problems = validator.validate_plan(plan, result.observations, result.charts,
                                       insight_observation_ids=refs)
    if problems:
        repairs.extend(recover_unscoped_topic_claims(plan, result, problems))
        problems = validator.validate_plan(plan, result.observations, result.charts,
                                           insight_observation_ids=refs)
    if problems:
        raise ValueError("Selected topic claims failed validation: " + "; ".join(p.message for p in problems))
    plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *repairs]))
    return plan


def recover_unscoped_topic_claims(plan: PresentationPlan, result: PipelineResult,
                                 issues: list[ValidationIssue]) -> list[str]:
    """Withdraw unresolved metric, category or period assertions to the same question.

    This does not choose missing endpoints or alter the model's selected data.
    A candidate must remove errors without adding any other validation error.
    The authored takeaway remains in the raw topic and in an audit note.
    """
    if not result.presentation_topics:
        return []
    from .presentation_summary_selection import rebuild_selected_topic_summary
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

    topics = {topic.id: topic for topic in result.presentation_topics.topics}
    summaries = {slide.id: slide for slide in plan.slides if slide.slide_type in {"summary", "executive_summary"}}
    affected = set()
    errors_by_topic: dict[str, list[str]] = {}
    for issue in issues:
        if issue.code != "direction_scope_ambiguous":
            continue
        slide_id = getattr(issue, "slide_id", None)
        summary = summaries.get(slide_id)
        matched = []
        if summary:
            index = getattr(issue, "bullet_index", None)
            if index is not None and index < len(summary.bullets):
                matches = [topic.id for topic in topics.values()
                           if summary.bullets[index] in {topic.takeaway, topic.title}]
                if len(matches) == 1:
                    matched = matches
        else:
            matched = [slide.theme_id for slide in plan.slides if slide.id == slide_id]
        for topic_id in matched:
            affected.add(topic_id)
            errors_by_topic.setdefault(topic_id, []).append(issue.message)
    if not affected:
        return []
    candidate = plan.model_copy(deep=True)
    notes = []
    for slide in candidate.slides:
        if slide.slide_type != "analysis" or slide.theme_id not in affected or slide.theme_id not in topics:
            continue
        question = slide.analytical_question.strip()
        if not question:
            continue
        notes.append(f"Slide {slide.id}: retained selected question because the takeaway lacked uniquely bound evidence. "
                     f"Authored takeaway: {topics[slide.theme_id].takeaway}")
        candidate.editorial_notes.append(_WITHHELD_PREFIX + json.dumps({
            "topic_id": slide.theme_id,
            "takeaway": topics[slide.theme_id].takeaway,
            "errors": list(dict.fromkeys(errors_by_topic[slide.theme_id])),
        }, ensure_ascii=False, sort_keys=True))
        slide.title = question
    rebuild_selected_topic_summary(result, candidate)
    # Summary reconstruction can reintroduce exact repeated-source records
    # from the retained topic catalog. Reapply the same provenance alignment
    # used by final claim preparation before comparing the candidate's errors;
    # this never merges conflicting values or relaxes the no-new-errors gate.
    from adaptive_document_agent.validation.presentation_evidence_alignment import align_redundant_slide_evidence
    notes.extend(align_redundant_slide_evidence(candidate, result.observations, result.charts))
    checked = ClaimValidator().validate_plan(candidate, result.observations, result.charts,
                                            insight_observation_ids=insight_inputs(result))
    key = lambda issue: (issue.code, issue.message, getattr(issue, "slide_id", None),
                         getattr(issue, "target_component", None), getattr(issue, "bullet_index", None))
    if len(checked) >= len(issues) or not {key(issue) for issue in checked} <= {key(issue) for issue in issues}:
        return []
    try:
        PresentationPlanValidator().validate(candidate, result)
    except ValueError:
        return []  # A question is not an exemption from number, source or scope checks.
    plan.slides = candidate.slides
    plan.editorial_notes = list(dict.fromkeys(candidate.editorial_notes))
    plan.editorial_status = "needs_review"
    for topic_id in sorted(withheld_topic_ids(candidate)):
        warning = ValidationIssue(
            code="presentation_topic_claims_withheld", severity="warning", stage="presentation",
            related_ids=[topic_id],
            message="Retained the model-selected question and evidence scope; an ambiguously bound takeaway "
                    "was withheld. Original wording and validation errors remain in the presentation audit.",
        )
        if not any(issue == warning for issue in result.validation_warnings):
            result.validation_warnings.append(warning)
    return notes
