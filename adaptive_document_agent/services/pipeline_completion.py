"""Completion checks also recognize older diagnostic-only cached results."""


def is_complete(result) -> bool:
    return (result.pipeline_state == 'complete'
        and not any(p.table_extraction_status == 'failed' for p in result.document.pages)
        and not any(
        issue.code in {'company_introduction_unavailable', 'editorial_stages_skipped'}
        for issue in result.validation_warnings))
