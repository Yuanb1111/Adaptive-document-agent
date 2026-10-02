"""Bind model-selected questions to native presentation evidence without an LLM round trip."""

from adaptive_document_agent.models import CompanyProfile, PipelineResult, PresentationPlan
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review
from .presentation_topic_selector import PresentationTopicSelector, series_directory
from .presentation_plan_recovery import PresentationPlanRecovery


def compile_topic_plan(result: PipelineResult) -> PresentationPlan:
    """Preserve semantic choices; Python only binds IDs, layout and validation.

    Invalid selections still fail into the existing observable recovery path.
    No model call, evidence check or review status is silently fabricated.
    """
    _, lookup = series_directory(result)
    from adaptive_document_agent.validation.topic_period_consistency import reconcile_topic_periods
    reconcile_topic_periods(result, lookup)
    from adaptive_document_agent.services.source_scope_completeness import reconcile_source_scopes
    reconcile_source_scopes(result, lookup)
    scope = {page for start, end in result.profile.analysis_page_ranges for page in range(start, end + 1)}
    PresentationTopicSelector._validate(result.presentation_topics, lookup, primary_pages=scope)
    plan = PresentationPlanRecovery().from_selected_topics(result, origin="topic_compilation")
    compiled_topics = {theme.id for theme in plan.themes}
    missing = [topic.id for topic in result.presentation_topics.topics if topic.id not in compiled_topics]
    if missing:
        raise ValueError("Selected topics require explicit recovery: " + ", ".join(missing))
    # Introduction extraction owns identity and background meaning. A profile
    # heading is not evidence of a company name; its validated draft is attached
    # by the orchestrator independently of this mechanical compilation.
    plan.company = CompanyProfile(document_type=result.profile.document_type)
    for slide in plan.slides:
        if slide.slide_type == "company_overview":
            slide.title = "Document at a Glance"
    # from_selected_topics owns the shared strict claim-recovery boundary.
    PresentationPlanValidator().validate(plan, result)
    plan = stamp_editorial_review(plan, result, origin="topic_compilation")
    for issue in result.validation_warnings:
        if issue.code in {"presentation_topics_unavailable", "presentation_topic_claims_withheld",
                          "presentation_closing_claim_withheld"}:
            plan.editorial_status = "needs_review"
            plan.editorial_notes.append(f"{', '.join(issue.related_ids)}: {issue.message}")
    return plan
