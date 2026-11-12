"""One monotonic spending deadline shared by all workers in an analysis attempt."""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
import math
import os

ANALYSIS_LIMIT_SECONDS = 15 * 60
_active = ContextVar('analysis_request_deadline', default=None)


class AnalysisTimeLimitExceeded(CancelledError):
    def __init__(self, limit_seconds=ANALYSIS_LIMIT_SECONDS):
        minutes = f'{limit_seconds / 60:g}'
        super().__init__(f'The {minutes}-minute analysis limit was reached. No further model requests '
                         'or retries will start. In-flight provider requests may still be billed.')
        self.attempts = []
        self.diagnostics = {'reason': 'analysis_time_limit', 'limit_seconds': limit_seconds}


class AnalysisDeadline:
    def __init__(self, *, clock=monotonic, started_at=None, limit_seconds=None):
        limit = float(os.getenv('ANALYSIS_TIMEOUT_SECONDS', str(ANALYSIS_LIMIT_SECONDS))
                      if limit_seconds is None else limit_seconds)
        if not math.isfinite(limit) or not 60 <= limit <= 7200:
            raise ValueError('ANALYSIS_TIMEOUT_SECONDS must be between 60 and 7200 seconds')
        self.limit_seconds = limit
        self.clock = clock
        self.started_at = clock() if started_at is None else started_at
        self.expires_at = self.started_at + self.limit_seconds

    @property
    def limit_label(self):
        return f'{self.limit_seconds / 60:g}-minute'

    @property
    def remaining(self):
        return max(0.0, self.expires_at - self.clock())

    def check(self):
        if not self.remaining:
            raise AnalysisTimeLimitExceeded(self.limit_seconds)


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
        raise AnalysisTimeLimitExceeded(deadline.limit_seconds)
    return min(configured, remaining)
