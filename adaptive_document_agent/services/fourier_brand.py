"""Colours for generated content in Fourier's light presentation template.

The VI Guidelines V1.0 (2024-06-28), pages 18–24, are authoritative for
brand colours. The Light Version Template EN_251217 additionally specifies
the technology blue. Original template artwork is intentionally not recoloured.
"""

PRIMARY = "7A24FD"
LIGHT_PURPLE = "AB76FF"
TECH_BLUE = "0086D1"
AMBER = "F5B923"
DEEP_BLUE = "2E3CED"
CYAN = "20EDF2"
DEEP_PURPLE = "190049"
PINK = "D71AFF"
MAGENTA = "A700FF"
MINT = "5BFF9D"
TEAL = "10E4A8"
LIME = "D4F44E"
ORANGE = "F37625"
CORAL = "F84932"
TEXT = "000000"
MUTED = "666666"  # 60% black, as specified for secondary text in the template.
SURFACE = "F6F7F7"
BORDER = "DBDCDC"
WHITE = "FFFFFF"

# Use saturated brand colours for marks, with contrasting labels. Light colours
# are suitable for filled marks; the renderer supplies black/white text separately.
CHART_COLORS = (PRIMARY, TECH_BLUE, AMBER, TEAL, LIGHT_PURPLE, DEEP_BLUE, CORAL, CYAN)
CHART_OVERFLOW_COLORS = (DEEP_PURPLE, PINK, ORANGE, MAGENTA, MINT, LIME)
ALL_CHART_COLORS = CHART_COLORS + CHART_OVERFLOW_COLORS
APPROVED_COLORS = frozenset((
    *CHART_COLORS, DEEP_PURPLE, PINK, MAGENTA, MINT, LIME, ORANGE,
    TEXT, MUTED, SURFACE, BORDER, WHITE,
))

# Historical generated colours and near-match template values are normalized
# only when generating new content; this never edits source artwork or evidence.
_LEGACY_COLORS = {
    "5B21B6": PRIMARY,
    "AB74FF": LIGHT_PURPLE,
    "F4B923": AMBER,
    "20ECF1": CYAN,
    "D68B13": AMBER,
    "158F78": TEAL,
    "B94E70": CORAL,
    "64748B": MUTED,
    "111827": TEXT,
    "6B7280": MUTED,
}


def normalize_brand_color(color: str | None, *, fallback: str = PRIMARY) -> str:
    """Return an approved generated colour, replacing legacy/unknown values."""
    if fallback not in APPROVED_COLORS:
        raise ValueError("The fallback must be a Fourier brand colour.")
    clean = (color or "").strip().removeprefix("#").upper()
    clean = _LEGACY_COLORS.get(clean, clean)
    return clean if clean in APPROVED_COLORS else fallback


def relative_luminance(color: str) -> float:
    """Calculate sRGB luminance for a six-digit RGB value."""
    clean = color.strip().removeprefix("#")
    if len(clean) != 6:
        raise ValueError("A colour must contain six hexadecimal digits.")
    channels = [int(clean[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def label_color(background: str) -> str:
    """Choose the more legible black/white label for an opaque RGB fill."""
    luminance = relative_luminance(background)
    black_contrast = (luminance + 0.05) / 0.05
    white_contrast = 1.05 / (luminance + 0.05)
    return TEXT if black_contrast >= white_contrast else WHITE
