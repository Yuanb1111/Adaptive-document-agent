"""Simple stage timer."""

from contextlib import contextmanager
import logging
from time import perf_counter
from typing import Iterator


def configure_timing_logging() -> None:
    """Expose only safe stage metadata in hosted logs, without SDK debug logs."""
    logger = logging.getLogger("adaptive_document_agent.timing")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@contextmanager
def record_timing(output: dict[str, int], stage: str) -> Iterator[None]:
    started = perf_counter()
    logger = logging.getLogger("adaptive_document_agent.timing")
    logger.info("stage_started stage=%s", stage)
    status = "failed"
    try:
        yield
        status = "complete"
    finally:
        output[stage] = int((perf_counter() - started) * 1000)
        logger.info("stage_finished stage=%s status=%s duration_ms=%d", stage, status, output[stage])
