"""Shared presentation tokens and deterministic semantic colours, independent of company."""

from hashlib import sha256
import math
from collections.abc import Iterable, Mapping

from .fourier_brand import (
    ALL_CHART_COLORS, CHART_COLORS, MUTED, PRIMARY, TEXT, normalize_brand_color,
)

FONT = "Arial"
DARK = TEXT
PURPLE = PRIMARY
PALETTE = CHART_COLORS
GUTTER = 0.28
MIN_BODY_PT = 12
CHART_TITLE_PT = 16
FOOTNOTE_PT = 9


def readable_axis_bounds(low: float, high: float) -> tuple[float, float, float]:
    """Round padded axis limits to regular ticks without changing data values."""
    span = high - low
    if not math.isfinite(span) or span <= 0:
        raise ValueError("Axis bounds must have a finite positive range.")
    raw_step = span / 5
    order = 10 ** math.floor(math.log10(raw_step))
    step = next(m * order for m in (1, 2, 2.5, 5, 10) if m * order >= raw_step)
    return math.floor(low / step) * step, math.ceil(high / step) * step, step


def semantic_color(key: str) -> str:
    """Return a stable approved fallback when a deck-wide mapping is unavailable."""
    clean = " ".join(key.casefold().split())
    return PALETTE[int.from_bytes(sha256(clean.encode("utf-8")).digest()[:4], "big") % len(PALETTE)]


def deck_color_map(
    keys: list[str], *, groups: Iterable[Iterable[str]] | None = None,
    preferred: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Assign colours once per deck, independent of slide/series iteration order.

    Equivalent case/whitespace spellings share a colour. The first eight distinct
    labels receive distinct colours when no co-occurrence groups are supplied.
    With groups, colours are reused only for labels that never appear together;
    unrelated single-series charts can therefore share the primary brand purple.
    Additional exact VI auxiliary colours handle unusually dense conflict graphs.
    """
    chart_groups = None if groups is None else [list(group) for group in groups]
    all_keys = list(keys)
    if chart_groups is not None:
        all_keys.extend(key for group in chart_groups for key in group)
    normalized = {key: " ".join(key.casefold().split()) for key in all_keys}
    neighbors: dict[str, set[str]] = {key: set() for key in normalized.values()}
    for group in ([all_keys] if chart_groups is None else chart_groups):
        members = {normalized[key] for key in group}
        for key in members:
            neighbors[key].update(members - {key})
    preferred_colors = {
        normalized[key]: normalize_brand_color(color, fallback=PRIMARY)
        for key, color in sorted((preferred or {}).items()) if key in normalized
    }
    assigned: dict[str, str] = {}
    palette = PALETTE if chart_groups is None else ALL_CHART_COLORS
    while len(assigned) < len(neighbors):
        key = min(
            (key for key in neighbors if key not in assigned),
            key=lambda value: (
                -len({assigned[item] for item in neighbors[value] if item in assigned}),
                -len(neighbors[value]), value,
            ),
        )
        used = {assigned[item] for item in neighbors[key] if item in assigned}
        candidates = [preferred_colors.get(key, PRIMARY), *palette]
        color = next((item for item in candidates if item in palette and item not in used), None)
        if color is None and chart_groups is not None:
            raise ValueError("Co-occurring chart series exceed the Fourier colour palette capacity.")
        assigned[key] = color or PALETTE[len(assigned) % len(PALETTE)]
    return {key: assigned[clean] for key, clean in normalized.items()}


def normalize_chart_color_map(
    color_map: Mapping[str, str], *, groups: Iterable[Iterable[str]] | None = None,
) -> dict[str, str]:
    """Migrate an old generated map once, resolving conflicts over all its keys."""
    return deck_color_map(list(color_map), groups=groups, preferred=color_map)


def chart_color(key: str, color_map: Mapping[str, str] | None = None) -> str:
    """Apply a deck assignment without accepting stale, off-brand chart colours."""
    fallback = semantic_color(key)
    color = normalize_brand_color((color_map or {}).get(key), fallback=fallback)
    return color if color in ALL_CHART_COLORS else fallback


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
