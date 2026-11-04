"""Resume validated upstream work after a retained briefing or integration failure."""
import json

from adaptive_document_agent.extraction.source_header_scope import source_header_issues
from adaptive_document_agent.services.company_summary import require_verified_introduction
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from adaptive_document_agent.validation.report_validator import ReportValidator

from .company_introduction import _has_valid_introduction
from .report_generator import ReportGenerator
from .retained_analysis import (
    SELECTION_CODE, RetainedAnalysisSelection, _validate_selection, can_reuse, fingerprint,
    selected_record, selection_context,
)


def retained_brief_reporting(previous, current, gateway, requested_focus=None, scope=None):
    """Return only the stages whose saved bindings still match current inputs."""
    if (previous is None or previous.pipeline_state != 'partial' or previous.retry_from != 'reporting'
            or (previous.failed_stage, previous.failure_details.get('component')) not in
                {('executive_brief', 'ExecutiveBrief'), ('source_integration', 'SourceIntegration')}
            or previous.presentation_topics is not None or not previous.presentation_plan
            or not previous.report_plan or not previous.charts or not previous.report_markdown
            or not previous.insights or not any(w.code == SELECTION_CODE for w in previous.validation_warnings)
            or getattr(getattr(gateway, 'settings', None), 'presentation_strategy', None) != 'retained_analysis'):
        return None
    if requested_focus is not None and requested_focus.strip() != (previous.profile.analysis_focus or '').strip():
        return None
    if scope is not None and [(p.start_page, p.end_page) for p in scope.page_ranges] != previous.profile.analysis_page_ranges:
        return None
    if any(getattr(current, key) != getattr(previous, key) for key in
           ('document', 'profile', 'observations', 'analysis_plan', 'analysis_results')):
        return None
    selection_issue = next(w for w in reversed(previous.validation_warnings) if w.code == SELECTION_CODE)
    candidate = current.model_copy(update={
        'insights': [i.model_copy(deep=True) for i in previous.insights],
        'report_plan': previous.report_plan.model_copy(deep=True),
        'charts': [c.model_copy(deep=True) for c in previous.charts],
        'presentation_plan': previous.presentation_plan.model_copy(deep=True),
        'validation_warnings': [*current.validation_warnings, selection_issue.model_copy(deep=True)],
    })
    try:
        record = selected_record(candidate)
        context = selection_context(candidate)
        if not can_reuse(gateway, previous) or record['contract'] != 1 or record['input_fingerprint'] != fingerprint(context):
            return None
        selection = RetainedAnalysisSelection.model_validate(record['selection'])
        _validate_selection(selection, context)
        slides = [slide for slide in candidate.presentation_plan.slides if slide.slide_type == 'analysis']
        if [slide.insight_ids for slide in slides] != [[key] for key in selection.ordered_insight_ids]:
            return None
        if not _has_valid_introduction(candidate.presentation_plan, candidate):
            return None
        require_verified_introduction(candidate)
        PresentationPlanValidator().validate(candidate.presentation_plan, candidate)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    for warning in source_header_issues(candidate.document):
        if warning not in candidate.validation_warnings:
            candidate.validation_warnings.append(warning)
    candidate.report_markdown = ReportGenerator().generate(candidate.profile, candidate.report_plan,
        candidate.insights, candidate.validation_warnings, observations=candidate.observations,
        charts=candidate.charts)
    candidate.validation_warnings.extend(
        ReportValidator().validate(candidate.report_markdown, candidate.analysis_results).issues)
    if previous.failed_stage == 'source_integration':
        candidate.executive_brief = checked_integration_input(previous, candidate)
    return candidate


def checked_integration_input(previous, current):
    """Recognize only the latest completed review of this exact pre-integration input."""
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    from .brief_item_repair import topic_coverage_errors
    from .brief_review_checkpoint import context_key

    brief = previous.executive_brief
    last = next((w for w in reversed(previous.validation_warnings)
                 if w.code == 'executive_brief_review_checkpoint'), None)
    if (brief is None or last is None or not brief.title.strip()
            or current.executive_brief is not None and current.executive_brief != brief):
        return None
    try:
        record = json.loads(last.message)
        context = record['source_context']
        if (record['semantic_approval'] is not True or record['pending'] != [] or record['unavailable'] != {}
                or record['checked'] != {str(i): [] for i in range(len(brief.items))}
                or record['candidate'] != brief.model_dump(mode='json')
                or context_key(None, None, current) != record['environment_key']
                or context_key(brief, context, current) != record['context_key']):
            return None
        topics = [(topic['title'], topic['pages']) for topic in context['selected_analysis_topics']]
        if (len(brief.items) > context['output_limits']['maximum_findings']
                or validate_executive_brief(brief, current) or topic_coverage_errors(brief, topics)):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return brief.model_copy(deep=True)
