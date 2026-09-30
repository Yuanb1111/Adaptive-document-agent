"""Retain selected questions when a takeaway lacks provable temporal bounds."""

from adaptive_document_agent.models import PipelineResult, PresentationPlan, ValidationIssue
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.presentation_provenance import insight_inputs
from .presentation_summary_selection import rebuild_selected_topic_summary


def recover_unscoped_topic_claims(plan: PresentationPlan, result: PipelineResult,
                                 issues: list[ValidationIssue]) -> list[str]:
    """Replace only unresolved period assertions with the topic's own question.

    This does not choose missing endpoints or alter the model's selected data.
    A candidate must remove errors without adding any other validation error.
    The authored takeaway remains in the raw topic and in an audit note.
    """
    topics = {topic.id: topic for topic in result.presentation_topics.topics}
    summaries = {slide.id: slide for slide in plan.slides if slide.slide_type in {"summary", "executive_summary"}}
    affected = set()
    for issue in issues:
        if issue.code != "direction_scope_ambiguous" or "explicit period" not in issue.message:
            continue
        slide_id = getattr(issue, "slide_id", None)
        summary = summaries.get(slide_id)
        if summary:
            index = getattr(issue, "bullet_index", None)
            if index is not None and index < len(summary.bullets):
                affected.update(topic.id for topic in topics.values()
                                if summary.bullets[index] in {topic.takeaway, topic.title})
        else:
            affected.update(slide.theme_id for slide in plan.slides if slide.id == slide_id)
    if not affected:
        return []
    candidate = plan.model_copy(deep=True)
    notes = []
    for slide in candidate.slides:
        if slide.slide_type != "analysis" or slide.theme_id not in affected:
            continue
        question = slide.analytical_question.strip()
        if not question:
            continue
        notes.append(f"Slide {slide.id}: retained selected question because the takeaway lacked explicit period evidence. "
                     f"Authored takeaway: {topics[slide.theme_id].takeaway}")
        slide.title = question
    rebuild_selected_topic_summary(result, candidate)
    checked = ClaimValidator().validate_plan(candidate, result.observations, result.charts,
                                            insight_observation_ids=insight_inputs(result))
    key = lambda issue: (issue.code, issue.message)
    if len(checked) >= len(issues) or not {key(issue) for issue in checked} <= {key(issue) for issue in issues}:
        return []
    plan.slides = candidate.slides
    plan.editorial_status = "needs_review"
    return notes
