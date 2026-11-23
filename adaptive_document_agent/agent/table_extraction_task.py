"""Run deterministic table extraction beside discovery without sharing mutations."""
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
from typing import Callable

from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.models.table import ExtractedTable


class PreparedTableExtraction:
    """Invocation-owned extraction future; only its caller attaches its result."""

    def __init__(self, raw: bytes, page_numbers: set[int] | None, *,
                 check_deadline: Callable[[], None] | None = None):
        self._cancelled = Event()
        self._extractor = TableExtractor(cancelled=self._cancelled, check_deadline=check_deadline)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='table-extraction')
        self._future: Future[dict[int, list[ExtractedTable]]] | None = None
        try:
            self._future = self._pool.submit(
                self._extractor.extract, raw, page_numbers=page_numbers)
        except BaseException:
            self.close()
            raise

    def result(self) -> tuple[TableExtractor, dict[int, list[ExtractedTable]]]:
        """Return the completed extractor and tables without mutating a document."""
        if self._future is None:
            raise RuntimeError('Table extraction was not submitted')
        return self._extractor, self._future.result()

    def close(self) -> None:
        """Cancel queued work and cooperatively drain any active PDF operation."""
        self._cancelled.set()
        if self._future is not None:
            self._future.cancel()
        self._pool.shutdown(wait=True, cancel_futures=True)


def prepare_table_extraction(raw: bytes, effective_pages: set[int] | None, *,
                             resources: ExitStack,
                             check_deadline: Callable[[], None] | None = None) -> PreparedTableExtraction:
    """Start extraction and tie its cancellation/cleanup to the pipeline stack.

    ``effective_pages`` must already include any requested appendix pages; ``None``
    retains the extractor's existing all-pages behavior. Cache reads and writes,
    page status, and document mutation remain the orchestrator's responsibility.
    """
    pages = set(effective_pages) if effective_pages is not None else None
    task = PreparedTableExtraction(raw, pages, check_deadline=check_deadline)
    resources.callback(task.close)
    return task
