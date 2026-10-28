"""Invocation-owned editorial work over stable, model-selected topics."""
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, get_ident
from time import perf_counter
from queue import SimpleQueue, Empty

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.llm import LLMGateway
from .executive_brief import ExecutiveBriefWriter


class PreparedBriefInputsChanged(ValueError):
    def __init__(self, fields):
        self.fields = tuple(fields)
        super().__init__('Prepared executive brief inputs changed: ' + ', '.join(self.fields))


def current_executive_brief(gateway, current, prepared=None):
    """Refresh once after final topic corrections; never accept stale copy."""
    if prepared is None:
        return ExecutiveBriefWriter(gateway).generate(current)
    try:
        return prepared.result(current)
    except PreparedBriefInputsChanged as exc:
        # Planning may correct topic copy while this independent worker runs.
        # A changed document, data, purpose or analysis is a different boundary:
        # those must still fail closed rather than reuse an inconsistent plan.
        if exc.fields != ('presentation_topics',):
            raise
        from adaptive_document_agent.models import ValidationIssue
        current.validation_warnings.append(ValidationIssue(code='executive_brief_snapshot_refreshed',
            stage='report', severity='info', message=
            'Presentation topics changed during parallel planning. Discarded the stale briefing '
            'and regenerated it once against the final topics with fresh source and meaning checks.'))
        return ExecutiveBriefWriter(gateway).generate(current)


class PreparedExecutiveBrief:
    """Generate on an isolated snapshot; only the caller attaches results/audits."""

    def __init__(self, gateway: LLMGateway, source: PipelineResult) -> None:
        self._caller = get_ident()
        self._source = source.model_copy(deep=True)
        self._cancelled = Event()
        self.duration_ms = 0
        self._progress = SimpleQueue()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='executive-brief')
        self._future: Future[ExecutiveBrief] = self._pool.submit(self._generate, gateway)

    def _generate(self, gateway: LLMGateway) -> ExecutiveBrief:
        started = perf_counter()
        try:
            from .brief_review_progress import brief_progress
            with brief_progress(self._progress.put):
                return ExecutiveBriefWriter(gateway).generate(self._source, cancelled=self._cancelled)
        finally:
            self.duration_ms = int((perf_counter() - started) * 1000)

    def result(self, current: PipelineResult) -> ExecutiveBrief:
        if get_ident() != self._caller:
            raise RuntimeError('Only the pipeline caller may attach the executive brief')
        try:
            from .brief_review_progress import report_brief_progress
            def drain():
                while True:
                    try:
                        message = self._progress.get_nowait()
                    except Empty:
                        break
                    report_brief_progress(message.removeprefix('Briefing review: '))
            while not self._future.done():
                drain()
                try:
                    self._future.result(timeout=0.25)
                except TimeoutError:
                    if self._future.done():
                        break
            drain()
            brief = self._future.result()
        finally:
            current.stage_details_ms.update(self._source.stage_details_ms)
            for issue in self._source.validation_warnings:
                if issue not in current.validation_warnings:
                    current.validation_warnings.append(issue.model_copy(deep=True))
        # Recovery must finish before this work starts. Fail closed if any input
        # used for editorial selection changed while the slide layout was built.
        changed = [field for field in ('document', 'profile', 'observations', 'insights',
                                      'analysis_results', 'presentation_topics')
                   if getattr(current, field) != getattr(self._source, field)]
        if changed:
            raise PreparedBriefInputsChanged(changed)
        from adaptive_document_agent.services.executive_brief import validate_executive_brief
        errors = validate_executive_brief(brief, current)
        if errors:
            raise ValueError('Prepared executive brief no longer matches source: ' + '; '.join(errors))
        return brief

    def close(self) -> None:
        self._cancelled.set()
        self._future.cancel()
        self._pool.shutdown(wait=True, cancel_futures=True)


@contextmanager
def prepare_executive_brief(gateway: LLMGateway, source: PipelineResult, *,
                            timings: dict[str, int]) -> Iterator[PreparedExecutiveBrief]:
    if gateway.discovery_workers <= 1:
        raise ValueError('Parallel editorial work requires a concurrent cloud gateway')
    prepared = PreparedExecutiveBrief(gateway, source)
    try:
        yield prepared
    finally:
        prepared.close()
        timings['executive_brief_duration'] = prepared.duration_ms
