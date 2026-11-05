"""Completion checks also recognize older diagnostic-only cached results."""
import json


def _latest_review_failure(result, reviewed, unresolved):
    latest = next((w for w in reversed(result.validation_warnings) if w.code in {reviewed, unresolved}), None)
    if latest and latest.code == unresolved:
        try:
            audit = json.loads(latest.message)
            reason = audit.get('reason') if isinstance(audit, dict) else None
            if isinstance(reason, str):
                return reason.strip()[:1500]
        except ValueError:
            pass  # Older checkpoints may contain plain-text warnings.
    return ''


def is_reporting_ready(result) -> bool:
    """Basic readiness before the final source integration review runs."""
    return (result.pipeline_state == 'complete'
        and not any(p.table_extraction_status == 'failed' for p in result.document.pages)
        and not any(
        issue.code in {'company_introduction_unavailable', 'editorial_stages_skipped'}
        for issue in result.validation_warnings))


def source_review_complete(result) -> bool:
    coverage = result.profile.source_coverage
    checks = coverage.checks_by_review_id() if coverage else {}
    if not checks:
        return True
    if result.executive_brief is None or any(
            c.status not in {'checked_found', 'checked_not_found'} for c in checks.values()):
        return False
    from adaptive_document_agent.agent.source_integration_review import resolved_source_check_ids
    return set(checks) <= resolved_source_check_ids(result, result.executive_brief)


def require_source_integration(result) -> None:
    if not source_review_complete(result):
        reason = _latest_review_failure(result, 'source_integration_review', 'source_integration_unresolved')
        raise ValueError('Supplementary source integration review is incomplete or stale. '
                         'Retry reporting before completing the analysis or exporting PowerPoint.'
                         + (f' Last review: {reason}' if reason else ''))


def topic_coverage_complete(result) -> bool:
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    from adaptive_document_agent.agent.topic_coverage_review import coverage_review_pending
    from .topic_review_status import topic_review_gaps
    return not topic_review_gaps(result) and not coverage_review_pending(result) and review_complete(result)


def require_topic_coverage(result) -> None:
    from adaptive_document_agent.agent.retained_analysis_review import require_retained_review
    require_retained_review(result)
    from .topic_review_status import require_topic_review
    require_topic_review(result)
    if not topic_coverage_complete(result):
        reason = _latest_review_failure(result, 'presentation_topic_coverage_review', 'presentation_topic_coverage_unresolved')
        raise ValueError('Presentation source coverage review is incomplete or stale. '
                         'Retry reporting before completing the analysis or exporting PowerPoint.'
                         + (f' Original coverage failure: {reason}' if reason else ''))


def is_complete(result) -> bool:
    # A retained failure is already incomplete. Do not invoke the same final
    # review gate again while the UI is trying to publish its diagnostics.
    if not is_reporting_ready(result):
        return False
    from adaptive_document_agent.agent.report_audit_scope import require_report_audit_scope
    try:
        require_report_audit_scope(result)
    except ValueError:
        return False
    return source_review_complete(result) and topic_coverage_complete(result)
