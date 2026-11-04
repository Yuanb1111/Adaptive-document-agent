"""Recover the catalog proposal after its final source review failed."""
import json

from adaptive_document_agent.models import PresentationTopic, PresentationTopicSelection
from .coverage_review_binding import completed_review_is_current
from .presentation_topic_selector import PresentationTopicSelector, series_directory
from .topic_coverage_review import TopicCoverageReview
from .topic_evidence_review import AUDIT_CODE, CoverageTopicReviewError, review_covered_topics, topic_binding


def topic_review_failure(result):
    return (result is not None and result.pipeline_state == 'partial' and result.retry_from == 'reporting'
            and result.failed_stage == 'presentation_coverage'
            and result.failure_details.get('component') == 'TopicEvidenceReview')


def retry_catalog_topics(previous, current, gateway, focus, scope):
    if (not topic_review_failure(previous) or not previous.insights or not previous.report_plan
            or getattr(getattr(gateway, 'settings', None), 'presentation_strategy', None) != 'full_catalog'
            or (focus is not None and focus.strip() != (previous.profile.analysis_focus or '').strip())
            or (scope is not None and [(r.start_page, r.end_page) for r in scope.page_ranges]
                != previous.profile.analysis_page_ranges)
            or any(getattr(previous, k) != getattr(current, k) for k in
                   ('document', 'profile', 'observations', 'analysis_plan', 'analysis_results'))):
        return None
    warnings = previous.validation_warnings
    index = next((i for i in range(len(warnings) - 1, -1, -1) if warnings[i].code in
        {'presentation_topic_coverage_unresolved', 'presentation_topic_coverage_review'}), None)
    if index is None or warnings[index].code != 'presentation_topic_coverage_review':
        return None
    try:
        record = json.loads(warnings[index].message)
        review = TopicCoverageReview.model_validate(record['review'])
        decisions = [d.series_id for d in review.coverage_decisions if d.reason.strip()]
        if len(set(decisions)) != len(review.coverage_decisions) or set(decisions) != set(record['candidate_series_ids']):
            return None
        selection = PresentationTopicSelection(topics=review.topics, omissions=review.omissions)
        topics = {t.id: t for t in selection.topics}
        if len(topics) != len(selection.topics) or not topics:
            return None
        # Earlier checkpoints kept post-coverage drafts and corrections in
        # the review log only. Restore copy, never a disposition or a verdict.
        legacy_corrections = set()
        checked_with_period_scope = set()
        for warning in warnings[index + 1:]:
            if warning.code != AUDIT_CODE:
                continue
            audit = json.loads(warning.message)
            if audit.get('column_scope_guidance'):
                checked_with_period_scope.update(audit.get('accepted_bindings', []))
            drafts = list(audit['original_topics'])
            for attempt in audit['attempts']:
                if attempt['phase'] == 'coverage_wording_correction' and attempt.get('response'):
                    drafts.extend(attempt['response']['topics'])
                    if not audit.get('column_scope_guidance'):
                        legacy_corrections.update(t['id'] for t in attempt['response']['topics'])
            for raw in drafts:
                topic = PresentationTopic.model_validate(raw)
                if topic.id not in topics or topic.series_ids != topics[topic.id].series_ids:
                    return None
                topics[topic.id] = topic
        selection.topics = list(topics.values())
        candidate = current.model_copy(update=dict(presentation_topics=selection, insights=previous.insights,
                                                    report_plan=previous.report_plan), deep=True)
        candidate.validation_warnings.extend(w.model_copy(deep=True) for w in warnings
            if w.code.startswith('presentation_') and w.code != 'presentation_topic_selection_failed'
            and w not in candidate.validation_warnings)
        _, lookup = series_directory(candidate)
        if not completed_review_is_current(candidate, record, lookup):
            return None
        primary = {n for a, b in candidate.profile.analysis_page_ranges for n in range(a, b + 1)}
        validate = PresentationTopicSelector.validator_for(candidate)
        validate(selection, lookup, primary_pages=primary)
        recheck = {tid for tid in legacy_corrections
                   if topic_binding(topics[tid], lookup, candidate) not in checked_with_period_scope}
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return None
    try:
        candidate.presentation_topics = review_covered_topics(selection, lookup, candidate, gateway,
            validate, primary_pages=primary, recheck_ids=recheck)
    except CoverageTopicReviewError as exc:
        candidate.pipeline_state, candidate.retry_from = 'partial', 'reporting'
        candidate.failed_stage = 'presentation_coverage'
        candidate.failure_details = dict(component='TopicEvidenceReview', error_type=type(exc).__name__,
                                         message=str(exc), retry_strategy='full_catalog')
    return candidate
