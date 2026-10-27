"""Retain completed analysis before a known failed source read wastes reporting."""
from time import perf_counter

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
from adaptive_document_agent.utils.timing import record_timing


def incomplete_source_reads(profile) -> list:
    ledger = profile.source_coverage
    return [check for check in ledger.checks if check.status not in
            {'checked_found', 'checked_not_found'}] if ledger else []


def retain_source_reading_failure(result, gateway, resources, prepared, timings,
                                  details, started, notify):
    pending = incomplete_source_reads(result.profile)
    if not pending:
        raise ValueError('A source-reading failure checkpoint requires unfinished source reads.')
    failures = [dict(section_id=c.section_id, pages=c.pages, status=c.status, reason=c.finding)
                for c in pending]
    message = 'Supplementary source reading is incomplete: ' + '; '.join(
        f"pages {c.pages}: {c.finding or c.status}" for c in pending)
    # Close invocation-owned background work; its original diagnostics survive.
    with record_timing(timings, 'background_drain'):
        resources.close()
    if prepared is not None:
        prepared.copy_audit(result)
    result.pipeline_state, result.retry_from = 'partial', 'reporting'
    result.pipeline_version = PIPELINE_VERSION
    result.failed_stage = 'source_reading'
    result.failure_details = dict(component='SourceReading', error_type='ValueError',
        message=message, source_checks=failures)
    result.validation_warnings.append(ValidationIssue(code='source_reading_failed',
        stage='discovery', severity='warning', message=message))
    result.llm_usage = list(gateway.usage) if gateway else []
    result.timings_ms, result.stage_details_ms = dict(timings), dict(details)
    result.pipeline_total_ms = int((perf_counter() - started) * 1000)
    notify('Supplementary source reading failed; retained analysis and skipped dependent report generation')
    return result
