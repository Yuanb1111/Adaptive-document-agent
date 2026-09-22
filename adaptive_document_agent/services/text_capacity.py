"""Deterministic readable text budgets, independent of document semantics."""

import re
from functools import lru_cache
from reportlab.pdfbase.pdfmetrics import stringWidth


@lru_cache(maxsize=2048)
def _glyph_width(char: str, size: float) -> float:
    # Helvetica has Arial-compatible Latin metrics. Keep a safety margin for
    # renderer differences; non-Latin glyphs conservatively occupy a full em.
    return (stringWidth(char, "Helvetica", size) * 1.12
            if ord(char) < 256 else size)


def wrap_copy(text: str, width: float, size: float) -> list[str]:
    """Wrap for capacity estimation while retaining every original character.

    These breaks are not inserted into the PowerPoint copy. Prefer whole words,
    but split oversized identifiers so continuation always makes progress.
    """
    limit = max(size, (width - .05) * 72)
    lines = []
    for paragraph in text.splitlines(keepends=True):
        body = paragraph.rstrip("\r\n")
        current, used = "", 0.0
        for token in re.findall(r"\S+\s*|\s+", body):
            needed = sum(_glyph_width(c, size) for c in token)
            if current and used + needed > limit:
                lines.append(current)
                current, used = "", 0.0
            for char in token:
                advance = _glyph_width(char, size)
                if current and used + advance > limit:
                    lines.append(current)
                    current, used = "", 0.0
                current += char
                used += advance
        lines.append(current + paragraph[len(body):])
    return lines or [""]
