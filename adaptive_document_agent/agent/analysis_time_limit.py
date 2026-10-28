"""Keep completed evidence and usage when the analysis spending budget expires."""
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.analysis_deadline import ANALYSIS_LIMIT_SECONDS, AnalysisTimeLimitExceeded
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION


def retain_timed_out_result(state, gateway, deadline):
    result = state.get('result')
    if result is None:
        raise AnalysisTimeLimitExceeded()
    result.pipeline_version = PIPELINE_VERSION
    result.pipeline_state = 'partial'
    result.retry_from = 'reporting' if state.get('reporting_ready') else None
    result.failed_stage = 'analysis_time_limit'
    result.failure_details = dict(component='AnalysisTimeLimit', error_type='AnalysisTimeLimitExceeded',
        message=str(AnalysisTimeLimitExceeded()), limit_seconds=ANALYSIS_LIMIT_SECONDS,
        stopped_stage=state.get('stage', ''))
    result.llm_usage = list(getattr(gateway, 'usage', []))
    result.pipeline_total_ms = round((deadline.clock() - deadline.started_at) * 1000)
    result.timings_ms.update(state.get('timings', {}))
    result.stage_details_ms.update(state.get('details', {}))
    recorded = {issue.model_dump_json() for issue in result.validation_warnings}
    for issue in state.get('issues', []):
        if issue.model_dump_json() not in recorded:
            result.validation_warnings.append(issue)
            recorded.add(issue.model_dump_json())
    result.validation_warnings.append(ValidationIssue(code='analysis_time_limit', stage='report',
        severity='warning', message=str(AnalysisTimeLimitExceeded())))
    return result
