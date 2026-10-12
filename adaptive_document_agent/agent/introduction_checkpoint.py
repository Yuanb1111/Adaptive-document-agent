"""Stop optional editorial work after a known mandatory-introduction failure."""
from time import perf_counter

from adaptive_document_agent.models import PresentationPlan, ValidationIssue
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
from adaptive_document_agent.utils.timing import record_timing


def failed_introduction_result(prepared, result, gateway, resources, timings, details,
                               pipeline_started, notify):
    # Caller checks failed() first: this never waits on a healthy ongoing read.
    try:
        prepared(PresentationPlan(title='Introduction verification'), result)
    except (LLMResponseError, ValueError) as exc:
        result.validation_warnings.append(ValidationIssue(
            code='company_introduction_unavailable', severity='error', stage='presentation',
            message='The independent company introduction could not be verified: ' + str(exc)[:500]))
    else:
        raise RuntimeError('Failed introduction checkpoint unexpectedly succeeded')
    # Privacy/cancellation exceptions deliberately propagate, with no fallback.
    with record_timing(timings, 'background_drain'):
        resources.close()
    result.validation_warnings.append(ValidationIssue(
        code='editorial_stages_skipped', severity='info', stage='report',
        message='Introduction verification failed. Retained extracted evidence and completed '
                'calculations; skipped insight writing, topic selection, briefing and localization.'))
    result.pipeline_version = PIPELINE_VERSION
    result.llm_usage = list(gateway.usage)
    result.timings_ms = dict(timings)
    result.stage_details_ms = dict(details)
    result.pipeline_total_ms = int((perf_counter() - pipeline_started) * 1000)
    notify('Company introduction failed; analysis diagnostics retained')
    return result
