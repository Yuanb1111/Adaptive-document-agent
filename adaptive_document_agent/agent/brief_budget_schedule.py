"""Avoid writing disposable briefs for already over-budget selected plans."""
from adaptive_document_agent.services.slide_budgets import report_budget, resolved_limits


def briefing_waits_for_budget(result, plan):
    """A scheduling hint only; native measurement remains the export authority.

    No topic is chosen or removed here. A known oversized draft should complete
    its model-owned physical selection before paying for independent copy that
    would immediately become stale. Ambiguous physical costs retain the normal
    concurrent briefing path.
    """
    if plan is None or not result.presentation_topics or not result.presentation_topics.topics:
        return False
    requirement = report_budget(result)
    if requirement is None:
        return False
    analysis_limits = resolved_limits(result.profile.report_requirements, section='analysis')
    if analysis_limits and sum(s.slide_type == 'analysis' for s in plan.slides) > min(analysis_limits):
        return True
    planned = [s for s in plan.slides if requirement.slide_scope == 'all' or s.slide_type != 'appendix']
    return len(planned) > requirement.max_slides


def complete_deferred_brief(gateway, result, *, progress=None):
    """A fitting native plan still needs exactly one independently checked brief."""
    if result.executive_brief is not None:
        return
    from .executive_brief import ExecutiveBriefWriter
    from .presentation_budget_refinement import measure, FinalBudgetBriefError
    from adaptive_document_agent.services.llm.exceptions import LLMResponseError
    from adaptive_document_agent.services.slide_budgets import require_exported_budgets
    if progress is not None:
        progress('Writing the evidence-bound executive briefing')
    try:
        from .brief_review_progress import brief_progress
        with brief_progress(progress):
            result.executive_brief = ExecutiveBriefWriter(gateway).generate(result)
    except (ValueError, LLMResponseError) as exc:
        raise FinalBudgetBriefError('Deferred briefing failed source checks: ' + str(exc)) from exc
    deck, _ = measure(result)
    require_exported_budgets(deck, result)


def native_briefing_waits_for_budget(result, plan):
    """Measure an attached introduction before paying for disposable briefing.

    This only schedules work. An incomplete pre-visual plan can be unmeasurable;
    it retains the normal path and all final source/physical export gates.
    """
    if briefing_waits_for_budget(result, plan):
        return True
    if (plan is None or not result.presentation_topics or not result.presentation_topics.topics
            or report_budget(result) is None or not plan.company.summary_pages
            or plan.company.summary_review is None or plan.company.summary_review.status != 'complete'):
        return False
    from .presentation_budget_refinement import measure
    from adaptive_document_agent.services.slide_budgets import require_exported_budgets
    snapshot = result.model_copy(deep=True)
    snapshot.presentation_plan = plan.model_copy(deep=True)
    try:
        deck, _ = measure(snapshot)
    except ValueError:
        # Failure to construct a preliminary projection is not evidence of a
        # budget violation and cannot establish source or semantic acceptance.
        return False
    try:
        require_exported_budgets(deck, snapshot)
    except ValueError:
        return True
    return False
