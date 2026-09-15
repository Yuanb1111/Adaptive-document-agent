"""Text quality helpers kept separate from PDF orchestration."""

import re


def text_quality(text: str) -> float:
    if not text:
        return 0.0
    printable = sum(character.isprintable() and not character.isspace() for character in text)
    garbled = len(re.findall(r"\ufffd|(?:.)\1{8,}", text))
    base = printable / max(len(text), 1)
    return max(0.0, min(1.0, base - garbled * 0.1))

