"""One monotonic spending deadline shared by all workers in an analysis attempt."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

ANALYSIS_LIMIT_SECONDS = 15 * 60
_active = ContextVar('analysis_request_deadline', default=None)


class AnalysisTimeLimitExceeded(CancelledError):
    def __init__(self):
        super().__init__('The 15-minute analysis limit was reached. No further model requests '
                         'or retries will start. In-flight provider requests may still be billed.')
        self.attempts = []
        self.diagnostics = {'reason': 'analysis_time_limit', 'limit_seconds': ANALYSIS_LIMIT_SECONDS}


class AnalysisDeadline:
    def __init__(self, *, clock=monotonic, started_at=None):
        self.clock = clock
        self.started_at = clock() if started_at is None else started_at
        self.expires_at = self.started_at + ANALYSIS_LIMIT_SECONDS

    @property
    def remaining(self):
        return max(0.0, self.expires_at - self.clock())

    def check(self):
        if not self.remaining:
            raise AnalysisTimeLimitExceeded()


@contextmanager
def request_deadline(deadline):
    token = _active.set(deadline)
    try:
        if deadline is not None:
            deadline.check()
        yield
    finally:
        _active.reset(token)


def request_timeout(configured):
    deadline = _active.get()
    if deadline is None:
        return configured
    remaining = deadline.remaining
    if not remaining:
        raise AnalysisTimeLimitExceeded()
    return min(configured, remaining)
