"""Completion checks also recognize older diagnostic-only cached results."""


def is_reporting_ready(result) -> bool:
    """Basic readiness before the final source integration review runs."""
    return (result.pipeline_state == 'complete'
        and not any(p.table_extraction_status == 'failed' for p in result.document.pages)
        and not any(
        issue.code in {'company_introduction_unavailable', 'editorial_stages_skipped'}
        for issue in result.validation_warnings))


def source_review_complete(result) -> bool:
    coverage = result.profile.source_coverage
    checks = list(coverage.checks) if coverage else []
    if not checks:
        return True
    if result.executive_brief is None or any(
            c.status not in {'checked_found', 'checked_not_found'} for c in checks):
        return False
    from adaptive_document_agent.agent.source_integration_review import resolved_source_check_ids
    return {c.section_id for c in checks} <= resolved_source_check_ids(result, result.executive_brief)


def require_source_integration(result) -> None:
    if not source_review_complete(result):
        raise ValueError('Supplementary source integration review is incomplete or stale. '
                         'Retry reporting before completing the analysis or exporting PowerPoint.')


def is_complete(result) -> bool:
    return is_reporting_ready(result) and source_review_complete(result)
