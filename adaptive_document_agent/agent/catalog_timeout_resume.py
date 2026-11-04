"""Restore completed reporting work after the shared analysis deadline."""
import json

from adaptive_document_agent.services.pipeline_completion import require_topic_coverage
from .coverage_review_binding import completed_review_is_current
from .presentation_topic_selector import PresentationTopicSelector, series_directory
from .topic_evidence_review import CoverageTopicReviewError, review_covered_topics


def catalog_timeout_reporting(previous, current, gateway, focus, scope):
    if (previous is None or previous.pipeline_state != 'partial'
            or not (previous.failed_stage == 'analysis_time_limit' or
                    ((previous.failed_stage, previous.failure_details.get('component')) in
                     {('executive_brief', 'ExecutiveBrief'), ('source_integration', 'SourceIntegration'),
                      ('presentation_budget', 'PresentationBudget')}
                     and previous.presentation_plan is not None))
            or previous.retry_from != 'reporting' or not previous.presentation_topics
            or not previous.presentation_topics.topics or not previous.report_plan
            or not previous.insights or not previous.report_markdown or not previous.charts
            or getattr(getattr(gateway, 'settings', None), 'presentation_strategy', None) != 'full_catalog'
            or (focus is not None and focus.strip() != (previous.profile.analysis_focus or '').strip())
            or (scope is not None and [(r.start_page, r.end_page) for r in scope.page_ranges]
                != previous.profile.analysis_page_ranges)):
        return None
    if any(getattr(previous, key) != getattr(current, key) for key in
           ('document', 'profile', 'observations', 'analysis_plan', 'analysis_results')):
        return None
    candidate = current.model_copy(update={key: getattr(previous, key) for key in
        ('presentation_topics', 'report_plan', 'insights', 'charts', 'report_markdown')}, deep=True)
    candidate.validation_warnings.extend(w.model_copy(deep=True) for w in previous.validation_warnings
        if w.code.startswith('presentation_') and w not in candidate.validation_warnings)
    latest = next((w for w in reversed(candidate.validation_warnings) if w.code in
        {'presentation_topic_coverage_review', 'presentation_topic_coverage_unresolved'}), None)
    _, lookup = series_directory(candidate)
    try:
        if (latest is None or latest.code != 'presentation_topic_coverage_review'
                or not completed_review_is_current(candidate, json.loads(latest.message), lookup)):
            return None
        require_topic_coverage(candidate)
        primary = {n for start, end in candidate.profile.analysis_page_ranges for n in range(start, end + 1)}
        validate = PresentationTopicSelector.validator_for(candidate)
        validate(candidate.presentation_topics, lookup, primary_pages=primary)
    except (ValueError, KeyError, TypeError):
        return None
    # Wording repaired after the catalog review still needs an independent
    # verdict. Recheck only bindings that no longer match their source rows.
    try:
        candidate.presentation_topics = review_covered_topics(candidate.presentation_topics, lookup, candidate,
            gateway, validate, primary_pages=primary)
    except CoverageTopicReviewError as exc:
        candidate.pipeline_state, candidate.retry_from = 'partial', 'reporting'
        candidate.failed_stage = 'presentation_coverage'
        candidate.failure_details = dict(component='TopicEvidenceReview', error_type=type(exc).__name__,
                                        message=str(exc))
    return candidate
