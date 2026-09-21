"""Shared presentation tokens and deterministic semantic colours, independent of company."""

from hashlib import sha256

FONT = "Arial"
DARK = "111827"
MUTED = "6B7280"
PURPLE = "5B21B6"
PALETTE = (PURPLE, "0086D1", "D68B13", "158F78", "AB74FF", "2E3CED", "B94E70", "64748B")
GUTTER = 0.28
MIN_BODY_PT = 12
CHART_TITLE_PT = 14
FOOTNOTE_PT = 9


def semantic_color(key: str) -> str:
    """A category keeps its colour when series or slides are reordered."""
    clean = " ".join(key.casefold().split())
    return PALETTE[int.from_bytes(sha256(clean.encode("utf-8")).digest()[:4], "big") % len(PALETTE)]


def deck_color_map(keys: list[str]) -> dict[str, str]:
    """Resolve palette collisions once for the whole deck, in stable key order."""
    output = {}
    used = set()
    for key in sorted(set(keys), key=str.casefold):
        preferred = semantic_color(key)
        color = next((c for c in (preferred, *PALETTE) if c not in used), preferred)
        output[key] = color
        used.add(color)
    return output
