"""Resume validated upstream work after a retained briefing or integration failure."""
import json

from adaptive_document_agent.extraction.source_header_scope import source_header_issues
from adaptive_document_agent.services.company_summary import require_verified_introduction
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from adaptive_document_agent.validation.report_validator import ReportValidator

from .analysis_time_limit import is_reporting_timeout
from .company_introduction import _has_valid_introduction
from .report_generator import ReportGenerator
from .retained_analysis import (
    SELECTION_CODE, RetainedAnalysisSelection, _validate_selection, can_reuse, fingerprint,
    selected_record, selection_context, selection_input_matches,
)


def _final_source_retry(previous):
    """Keep a draft whose selection was accepted, but grant no source verdict.

    A renderer/validator correction must not force the writer to replace every
    previously bound page. The normal publication gate reviews the whole draft
    again; content still rejected by that gate remains a failed attempt.
    """
    if (previous is None or previous.failed_stage != 'presentation_coverage'
            or previous.failure_details.get('component') != 'PresentationCoverage'):
        return False
    from .retained_selection_feedback import can_retry_source_review
    if can_retry_source_review(previous):
        # A fresh rejection must reach the existing bounded page-correction
        # route. Reusing its unchanged plan would repeat the same failure.
        return False
    from .retained_analysis_review import RetainedAnalysisReview, REVIEW_CODE
    latest = next((w for w in reversed(previous.validation_warnings) if w.code == REVIEW_CODE), None)
    try:
        record = json.loads(latest.message)
        review = RetainedAnalysisReview.model_validate(record['review'])
        ids = {s.id for s in previous.presentation_plan.slides if s.slide_type == 'analysis'}
        return (record['contract'] == 1 and review.omissions_accepted and bool(ids)
                and len(review.verdicts) == len(ids) and {v.slide_id for v in review.verdicts} == ids)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def retained_brief_reporting(previous, current, gateway, requested_focus=None, scope=None):
    """Return only the stages whose saved bindings still match current inputs."""
    timed_out = is_reporting_timeout(previous)
    budget_retry = (previous is not None and previous.failed_stage == 'presentation_budget'
                    and previous.failure_details.get('component') == 'PresentationBudget')
    from .retained_selection_feedback import can_retry_source_review
    source_copy_retry = previous is not None and can_retry_source_review(previous)
    if (previous is None or previous.pipeline_state != 'partial' or previous.retry_from != 'reporting'
            or ((previous.failed_stage, previous.failure_details.get('component')) not in
                {('executive_brief', 'ExecutiveBrief'), ('source_integration', 'SourceIntegration')}
                and not source_copy_retry and not budget_retry and not timed_out and not _final_source_retry(previous))
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
        'validation_warnings': [*current.validation_warnings,
                                *(w.model_copy(deep=True) for w in previous.validation_warnings
                                  if w.code == 'retained_selection_coverage'),
                                selection_issue.model_copy(deep=True)],
    })
    if budget_retry or source_copy_retry:
        candidate.validation_warnings.extend(w.model_copy(deep=True) for w in previous.validation_warnings
            if w.code in {'source_integration_review', 'source_integration_unresolved',
                          'executive_brief_review_checkpoint', 'report_audit_scope_review'})
    try:
        record = selected_record(candidate)
        context = selection_context(candidate)
        if not can_reuse(gateway, previous) or record['contract'] != 1 or not selection_input_matches(record, context, candidate):
            return None
        selection = RetainedAnalysisSelection.model_validate(record['selection'])
        _validate_selection(selection, context)
        slides = [slide for slide in candidate.presentation_plan.slides if slide.slide_type == 'analysis']
        if [slide.insight_ids for slide in slides] != [[key] for key in selection.ordered_insight_ids]:
            return None
        if not _has_valid_introduction(candidate.presentation_plan, candidate):
            return None
        require_verified_introduction(candidate)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if timed_out and record.get('source_authoring'):
        from .retained_page_sources import AuthoredPageErrors, validate_authored_pages
        try:
            validate_authored_pages(selection, context, candidate)
        except AuthoredPageErrors as errors:
            from .retained_timeout_copy import repair_timeout_copy
            from adaptive_document_agent.services.llm.exceptions import LLMResponseError
            try:
                repair_timeout_copy(gateway, candidate, selection, context, errors)
            except (ValueError, LLMResponseError) as exc:
                candidate.pipeline_state, candidate.retry_from = 'partial', 'reporting'
                candidate.failed_stage = 'presentation_selection'
                candidate.failure_details = dict(component='RetainedAnalysisSelection',
                    error_type=type(exc).__name__, message=str(exc))
                return candidate
        except ValueError:
            return None
    try:
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
    if budget_retry or source_copy_retry:
        candidate.executive_brief = checked_published_brief(previous, candidate)
        if candidate.executive_brief is None:
            return None
        if source_copy_retry:
            from .retained_source_retry import repair_retained_source_copy
            from adaptive_document_agent.services.llm.exceptions import LLMResponseError
            try:
                repair_retained_source_copy(gateway, candidate, previous)
            except (LLMResponseError, ValueError) as exc:
                # Keep the last complete source-bound shell when the bounded
                # local edit fails. A partially merged selection is not a new
                # publication checkpoint and cannot inherit any approval.
                failed = previous.model_copy(deep=True)
                failed.failure_details = {**failed.failure_details,
                    'message': f'Retained publication-copy correction failed: {exc}'}
                return failed
    elif previous.failed_stage == 'source_integration' or timed_out:
        candidate.executive_brief = checked_integration_input(previous, candidate)
    return candidate


def checked_published_brief(previous, current):
    """Reuse identical source-complete published copy, never a failed draft verdict."""
    from adaptive_document_agent.services.pipeline_completion import source_review_complete
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    from .source_integration_review import _fingerprint
    if previous is not None and not (previous.profile.source_coverage
            and previous.profile.source_coverage.checks_by_review_id()):
        return checked_integration_input(previous, current)
    brief = previous.executive_brief if previous is not None else None
    if (brief is None or not source_review_complete(previous)
            or current.executive_brief is not None and current.executive_brief != brief
            or current.presentation_plan is None or previous.presentation_plan is None
            or current.presentation_plan.company != previous.presentation_plan.company
            or [s for s in current.presentation_plan.slides if s.slide_type != 'analysis']
                != [s for s in previous.presentation_plan.slides if s.slide_type != 'analysis']
            or any(getattr(previous, key) != getattr(current, key) for key in
                   ('document', 'observations', 'analysis_plan', 'analysis_results', 'insights', 'report_plan', 'charts'))):
        return None
    try:
        record = selected_record(current)
        if (not record or not selection_input_matches(record, selection_context(current), current)
                or record['selection']['ordered_insight_ids'] != selected_record(previous)['selection']['ordered_insight_ids']
                or _fingerprint(previous, brief) != _fingerprint(current, brief)
                or validate_executive_brief(brief, current)):
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return brief.model_copy(deep=True)


def checked_integration_input(previous, current):
    """Recognize only the latest completed review of this exact pre-integration input."""
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    from .brief_item_repair import topic_coverage_errors
    from .brief_review_checkpoint import checkpoint_context_matches

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
                or not checkpoint_context_matches(record, brief, current)):
            return None
        topics = [(topic['title'], topic['pages']) for topic in context['selected_analysis_topics']]
        if (len(brief.items) > context['output_limits']['maximum_findings']
                or validate_executive_brief(brief, current) or topic_coverage_errors(brief, topics)):
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return brief.model_copy(deep=True)
