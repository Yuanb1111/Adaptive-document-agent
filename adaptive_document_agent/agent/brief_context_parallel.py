"""Run a context-only reviewer alongside the source gate through the same gateway."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from queue import Empty, SimpleQueue
from threading import Event
from time import perf_counter

from .brief_context_review import review_context
from .brief_review_progress import brief_progress, report_brief_progress


class _Cancellation:
    def __init__(self, parent):
        self.parent = parent
        self.local = Event()

    def is_set(self):
        return self.local.is_set() or (self.parent is not None and self.parent.is_set())


@contextmanager
def prepared_context_review(gateway, messages, indices, record, *, cancelled=None):
    """Only the caller attaches verdicts; local/stateful gateways remain serial."""
    stop = _Cancellation(cancelled)
    queue = SimpleQueue()
    pool = None
    future = None
    completed = None

    def run():
        if stop.is_set():
            raise CancelledError('Brief context review cancelled')
        started = perf_counter()
        try:
            with brief_progress(queue.put):
                return review_context(gateway, messages, indices, record, stop)
        finally:
            record['duration_ms'] = round((perf_counter() - started) * 1000)

    def drain():
        while True:
            try:
                message = queue.get_nowait()
            except Empty:
                return
            report_brief_progress(message.removeprefix('Briefing review: '))

    def finish():
        nonlocal completed
        if completed is not None:
            return completed
        if future is None:
            completed = run()
        else:
            while not future.done():
                drain()
                try:
                    future.result(timeout=0.25)
                except TimeoutError:
                    if future.done():
                        break
            completed = future.result()
        drain()
        return completed

    try:
        if getattr(gateway, 'discovery_workers', 1) > 1:
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='brief-context')
            future = pool.submit(copy_context().run, run)
        yield finish
    finally:
        stop.local.set()
        if future is not None:
            future.cancel()
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        drain()
