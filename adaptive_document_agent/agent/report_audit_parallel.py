"""Bound independent source-group review without bypassing LLMGateway controls."""
from concurrent.futures import CancelledError, FIRST_COMPLETED, ThreadPoolExecutor, wait
from queue import Empty, Queue
from threading import Event


class _CancellableGateway:
    """Keep provider/privacy/admission decisions on the original gateway."""
    def __init__(self, gateway, cancelled):
        self._gateway = gateway
        self._cancelled = cancelled

    def generate_structured(self, *args, **kwargs):
        if self._cancelled.is_set():
            raise CancelledError('Audit review cancelled after another source group failed')
        return self._gateway.generate_structured(*args, **kwargs, cancelled=self._cancelled)


def review_groups_concurrently(gateway, groups, partitions, run, *, workers, progress=None):
    """At most two independent groups; progress and record merging stay on caller."""
    cancelled = Event()
    messages = Queue()
    proxy = _CancellableGateway(gateway, cancelled)
    errors = []
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='report-audit')
    futures = []

    def drain_progress():
        while True:
            try:
                message = messages.get_nowait()
            except Empty:
                return
            if progress:
                progress(message)

    try:
        futures = [pool.submit(run, ids, partition, proxy, messages.put, cancelled)
                   for ids, partition in zip(groups, partitions)]
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
            drain_progress()
            for future in done:
                try:
                    future.result()
                except Exception as exc:
                    errors.append(exc)
                    cancelled.set()
                    for other in pending:
                        other.cancel()
        if errors:
            raise next((error for error in errors if not isinstance(error, CancelledError)), errors[0])
    finally:
        cancelled.set()
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        drain_progress()
