"""Simple stage timer."""

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator


@contextmanager
def record_timing(output: dict[str, int], stage: str) -> Iterator[None]:
    started = perf_counter()
    try:
        yield
    finally:
        output[stage] = int((perf_counter() - started) * 1000)

