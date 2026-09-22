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


def compact_template_branding(presentation) -> None:
    """Scale the bundled template's horizontal header logos like the reference.

    Only header pictures with the logo's geometry are touched. Image bytes,
    footer artwork, large cover artwork, and user-supplied templates stay intact.
    """
    from pptx.util import Inches
    for layout in presentation.slide_layouts:
        for shape in layout.shapes:
            if not hasattr(shape, "image") or not shape.height:
                continue
            ratio = shape.width / shape.height
            if (shape.left > presentation.slide_width * .70 and shape.top < Inches(.8)
                    and shape.height < Inches(.5) and 5 < ratio < 12):
                shape.width = Inches(1.05)
                shape.height = Inches(1.05 / ratio)
                shape.left = presentation.slide_width - Inches(1.60)
                shape.top = Inches(.23)
