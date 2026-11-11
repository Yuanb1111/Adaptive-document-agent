"""Retry final display preparation after all source and content reviews passed."""
from collections.abc import Callable
from time import perf_counter

from adaptive_document_agent.models import AnalysisScopePreview, PipelineResult
from adaptive_document_agent.services.company_summary import require_verified_introduction
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.pipeline_completion import (
    is_complete, require_source_integration, require_topic_coverage,
)
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from .report_audit_scope import require_report_audit_scope


def retry_final_layout(
    previous: PipelineResult, gateway: LLMGateway | None, *, requested_focus: str | None = None,
    scope: AnalysisScopePreview | None = None, progress: Callable[[str], None] | None = None,
) -> PipelineResult | None:
    """Reuse only a source-valid report with current independent approvals."""
    if (previous.failed_stage != 'final_presentation_layout'
            or previous.failure_details.get('component') != 'FinalPresentationLayout'
            or previous.executive_brief is None or previous.presentation_plan is None
            or (requested_focus is not None
                and requested_focus.strip() != (previous.profile.analysis_focus or '').strip())
            or (scope is not None and [(p.start_page, p.end_page) for p in scope.page_ranges]
                != previous.profile.analysis_page_ranges)):
        return None
    candidate = previous.model_copy(deep=True)
    try:
        require_verified_introduction(candidate)
        PresentationPlanValidator().validate(candidate.presentation_plan, candidate)
        require_report_audit_scope(candidate)
        require_source_integration(candidate)
        require_topic_coverage(candidate)
        if validate_executive_brief(candidate.executive_brief, candidate):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    from .final_presentation_layout import check_final_presentation_layout
    from .report_localization import prepare_report_language
    from adaptive_document_agent.services.customization_checks import check_requirements
    started = perf_counter()
    notify = progress or (lambda _: None)
    notify('Retrying final display preparation with source-reviewed report content')
    prepare_report_language(gateway, candidate, progress=notify)
    check_requirements(candidate)
    if check_final_presentation_layout(candidate):
        candidate.pipeline_state = 'complete'
        candidate.retry_from = candidate.failed_stage = None
        candidate.failure_details = {}
        if not is_complete(candidate):
            raise ValueError('The final display retry invalidated a source or content review')
        notify('Complete')
    else:
        notify('Final display validation incomplete; diagnostics and retry checkpoint retained')
    candidate.llm_usage = list(getattr(gateway, 'usage', []))
    candidate.pipeline_total_ms = round((perf_counter() - started) * 1000)
    candidate.timings_ms = {'final_display_retry': candidate.pipeline_total_ms}
    return candidate
