"""Invocation-owned editorial work over stable, model-selected topics."""
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, get_ident
from time import perf_counter

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.executive_brief import ExecutiveBrief
from adaptive_document_agent.services.llm import LLMGateway
from .executive_brief import ExecutiveBriefWriter


class PreparedExecutiveBrief:
    """Generate on an isolated snapshot; only the caller attaches results/audits."""

    def __init__(self, gateway: LLMGateway, source: PipelineResult) -> None:
        self._caller = get_ident()
        self._source = source.model_copy(deep=True)
        self._cancelled = Event()
        self.duration_ms = 0
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='executive-brief')
        self._future: Future[ExecutiveBrief] = self._pool.submit(self._generate, gateway)

    def _generate(self, gateway: LLMGateway) -> ExecutiveBrief:
        started = perf_counter()
        try:
            return ExecutiveBriefWriter(gateway).generate(self._source, cancelled=self._cancelled)
        finally:
            self.duration_ms = int((perf_counter() - started) * 1000)

    def result(self, current: PipelineResult) -> ExecutiveBrief:
        if get_ident() != self._caller:
            raise RuntimeError('Only the pipeline caller may attach the executive brief')
        try:
            brief = self._future.result()
        finally:
            current.stage_details_ms.update(self._source.stage_details_ms)
            for issue in self._source.validation_warnings:
                if issue not in current.validation_warnings:
                    current.validation_warnings.append(issue.model_copy(deep=True))
        # Recovery must finish before this work starts. Fail closed if any input
        # used for editorial selection changed while the slide layout was built.
        for field in ('document', 'profile', 'observations', 'insights', 'analysis_results', 'presentation_topics'):
            if getattr(current, field) != getattr(self._source, field):
                raise ValueError('Prepared executive brief inputs changed: ' + field)
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
