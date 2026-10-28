"""Invocation-local briefing progress; background workers only enqueue events."""
from contextlib import contextmanager
from contextvars import ContextVar

_callback = ContextVar('brief_review_progress', default=None)


@contextmanager
def brief_progress(callback):
    token = _callback.set(callback)
    try:
        yield
    finally:
        _callback.reset(token)


def report_brief_progress(message):
    callback = _callback.get()
    if callback is not None:
        callback('Briefing review: ' + message)
