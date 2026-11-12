"""Overlap independent original-page review with supplementary brief work."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager
from time import perf_counter

from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError


class PreparedRetainedReview:
    """Review an isolated snapshot; attach only at an identical final boundary."""

    def __init__(self, gateway, result):
        from .retained_analysis import fingerprint
        from .retained_analysis_review import review_context
        self.snapshot = result.model_copy(deep=True)
        self.fingerprint = fingerprint(review_context(self.snapshot))
        self.duration_ms = 0
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='retained-source-review')
        self.future = self.pool.submit(self._review, gateway)

    def _review(self, gateway):
        from .retained_analysis_review import review_retained_analysis
        started = perf_counter()
        try:
            review_retained_analysis(gateway, self.snapshot)
        finally:
            self.duration_ms = round((perf_counter() - started) * 1000)

    def attach(self, result):
        """Return a bound rejection for existing repairs, never auto-approve it."""
        from .retained_analysis import fingerprint
        from .retained_analysis_review import review_context, REVIEW_CODE
        error = None
        try:
            self.future.result()
        except (PrivacyViolationError, CancelledError):
            raise
        except ValueError as exc:
            error = exc
        result.stage_details_ms['retained_analysis_review_duration'] = self.duration_ms
        if fingerprint(review_context(result)) != self.fingerprint:
            return None  # Current final pages must earn their own fresh review.
        record = next((w for w in reversed(self.snapshot.validation_warnings) if w.code == REVIEW_CODE), None)
        if record is not None and record not in result.validation_warnings:
            result.validation_warnings.append(record.model_copy(deep=True))
        return error

    def close(self):
        self.future.cancel()
        self.pool.shutdown(wait=True, cancel_futures=True)


@contextmanager
def prepare_retained_review(gateway, result):
    from .retained_analysis import selected_record
    record = selected_record(result)
    # A physical selection can depend on audience briefing coverage. Keep that
    # route serial until source integration and its whole-deck budget settle.
    if (getattr(gateway, 'discovery_workers', 1) <= 1 or not record
            or record.get('physical_budget')):
        yield None
        return
    prepared = PreparedRetainedReview(gateway, result)
    try:
        yield prepared
    finally:
        prepared.close()
