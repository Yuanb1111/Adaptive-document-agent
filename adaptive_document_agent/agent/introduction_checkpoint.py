"""Stop optional editorial work after a known mandatory-introduction failure."""
from concurrent.futures import CancelledError
from time import perf_counter

from adaptive_document_agent.models import PresentationPlan, ValidationIssue
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
from adaptive_document_agent.utils.timing import record_timing


class IntroductionVerificationFailed(Exception):
    """A mandatory prerequisite failed; optional editorial recovery cannot fix it."""


class _EditorialCancellation:
    def __init__(self, guard, cancelled):
        self.guard, self.cancelled = guard, cancelled

    def is_set(self):
        if self.cancelled is not None and self.cancelled.is_set():
            return True
        self.guard.check()
        return False


class IntroductionGuardedGateway:
    """Invocation-local admission guard over the ordinary, unchanged gateway.

    Introduction generation uses the original gateway. Only dependent report,
    topic, slide and briefing requests use this view. Existing requests drain;
    queued/new requests cannot start after a known mandatory failure.
    """

    def __init__(self, gateway, prepared):
        self.gateway, self.prepared = gateway, prepared

    def __getattr__(self, name):
        return getattr(self.gateway, name)

    def check(self):
        try:
            self.prepared.raise_if_failed()
        except (LLMResponseError, ValueError) as exc:
            raise IntroductionVerificationFailed(str(exc)) from exc

    def generate_structured(self, *args, **kwargs):
        cancelled = kwargs.get('cancelled')
        if cancelled is not None and cancelled.is_set():
            raise CancelledError('Editorial operation was cancelled before admission')
        self.check()
        kwargs['cancelled'] = _EditorialCancellation(self, cancelled)
        return self.gateway.generate_structured(*args, **kwargs)

    def generate_text(self, *args, **kwargs):
        self.check()
        return self.gateway.generate_text(*args, **kwargs)


def failed_introduction_result(prepared, result, gateway, resources, timings, details,
                               pipeline_started, notify, *, before_scoring=False,
                               failure=None, skipped=None):
    # Caller checks failed() first: this never waits on a healthy ongoing read.
    if failure is None:
        try:
            prepared(PresentationPlan(title='Introduction verification'), result)
        except (LLMResponseError, ValueError) as exc:
            failure = exc
        else:
            raise RuntimeError('Failed introduction checkpoint unexpectedly succeeded')
    else:
        prepared.copy_audit(result)
    from .introduction_failure import introduction_failure_details, introduction_failure_message
    result.failed_stage, result.failure_details = introduction_failure_details(result, failure)
    failure_message = introduction_failure_message(result.failed_stage, result.failure_details)
    result.validation_warnings.append(ValidationIssue(
        code='company_introduction_unavailable', severity='error', stage='presentation',
        message='The independent company introduction could not be verified. ' + failure_message))
    # Privacy/cancellation exceptions deliberately propagate, with no fallback.
    with record_timing(timings, 'background_drain'):
        resources.close()
    result.validation_warnings.append(ValidationIssue(
        code='editorial_stages_skipped', severity='info', stage='report',
        message=('Introduction verification failed. Retained extracted evidence and any completed '
                 'calculations; skipped ' + (skipped if skipped is not None else
                 ('candidate scoring, ' if before_scoring else '') +
                 'insight writing, topic selection, briefing and localization.'))))
    result.pipeline_version = PIPELINE_VERSION
    result.pipeline_state = 'partial'
    result.retry_from = 'candidate_scoring' if before_scoring else 'reporting'
    result.llm_usage = list(gateway.usage)
    result.timings_ms = dict(timings)
    result.stage_details_ms = dict(details)
    result.pipeline_total_ms = int((perf_counter() - pipeline_started) * 1000)
    notify(failure_message)
    return result
