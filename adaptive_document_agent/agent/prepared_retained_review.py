"""Overlap independent original-page review with supplementary brief work."""
import json
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager
from time import perf_counter

from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError


class SavedRetainedReview:
    def __init__(self, issue, identity, failure):
        self.issue = issue
        self.identity = identity
        self.failure = failure

    def attach(self, result):
        from .retained_analysis import fingerprint
        from .retained_analysis_review import REVIEW_CODE, review_context
        if fingerprint(review_context(result)) != self.identity:
            return None
        latest = next((w for w in reversed(result.validation_warnings) if w.code == REVIEW_CODE), None)
        if latest is not None and latest != self.issue:
            return None
        if latest is None:
            result.validation_warnings.append(self.issue.model_copy(deep=True))
        return self.failure


def _saved_review(previous, result):
    from .retained_analysis import fingerprint
    from .retained_analysis_review import RetainedAnalysisReview, REVIEW_CODE, review_context
    if (previous is None or previous.pipeline_state != 'partial' or previous.failed_stage != 'source_integration'
            or previous.failure_details.get('component') != 'SourceIntegration'):
        return None
    issue = next((w for w in reversed(previous.validation_warnings) if w.code == REVIEW_CODE), None)
    if issue is None:
        return None
    try:
        audit = json.loads(issue.message)
        context = review_context(result)
        identity = fingerprint(context)
        if audit['contract'] != 1 or audit['fingerprint'] != identity:
            return None
        expected = {slide['id'] for slide in context['slides']}
        raw = RetainedAnalysisReview.model_validate(audit['review'])
        review = RetainedAnalysisReview.model_validate(audit['effective_review']) if 'effective_review' in audit else raw
        for outcome in (raw, review):
            if len(outcome.verdicts) != len(expected) or {v.slide_id for v in outcome.verdicts} != expected:
                return None
        reasons = [v.reason for v in review.verdicts if not v.accepted]
        if not review.omissions_accepted:
            reasons.insert(0, review.omission_reason)
        if any(v.accepted and v.assurance_changes for v in review.verdicts):
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return SavedRetainedReview(issue, identity, ValueError(' '.join(reasons)) if reasons else None)


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


def _fits_before_review(result):
    """Defer the source review when native pagination already requires a new selection."""
    from adaptive_document_agent.services.slide_budgets import require_exported_budgets, resolved_limits
    from .presentation_budget_refinement import measure

    requirements = result.profile.report_requirements
    if not any(resolved_limits(requirements, section=section) for section in ('report', 'introduction', 'analysis')):
        return True
    # Native measurement annotates the result's export trace. Source integration
    # and its final measurement must see only their own snapshot.
    preview = result.model_copy(deep=True)
    try:
        presentation, _ = measure(preview)
        require_exported_budgets(presentation, preview)
    except ValueError:
        return False
    return True


@contextmanager
def prepare_retained_review(gateway, result, *, previous=None):
    from .retained_analysis import selected_record
    record = selected_record(result)
    # A physical selection can depend on audience briefing coverage. Keep that
    # route serial until source integration and its whole-deck budget settle.
    if not record or record.get('physical_budget'):
        yield None
        return
    saved = _saved_review(previous, result)
    if saved is None and (getattr(gateway, 'discovery_workers', 1) <= 1 or not _fits_before_review(result)):
        yield None
        return
    prepared = saved or PreparedRetainedReview(gateway, result)
    try:
        yield prepared
    finally:
        completed = saved is not None
        if saved is None:
            prepared.close()
            completed = (not prepared.future.cancelled()
                         and isinstance(prepared.future.exception(), (type(None), ValueError)))
        if completed and result.failed_stage == 'source_integration' and result.pipeline_state == 'partial':
            try:
                prepared.attach(result)
            except (ValueError, TypeError, KeyError, AttributeError):
                # An unusable snapshot cannot replace the independent source failure.
                pass
