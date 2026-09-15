"""Extensible OCR contract; no engine is silently selected."""

from abc import ABC, abstractmethod
from typing import NamedTuple


class OCRResult(NamedTuple):
    text: str
    confidence: float
    blocks: list[dict[str, object]]


class OCRAdapter(ABC):
    @abstractmethod
    def extract(self, image_bytes: bytes, *, page_number: int) -> OCRResult:
        """Extract page text without changing the original page evidence."""

