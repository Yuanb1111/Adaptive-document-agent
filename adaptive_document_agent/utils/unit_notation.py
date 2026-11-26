"""Literal unit syntax shared by source extraction and display formatting."""

# A thousands header may print the apostrophe on either side of three zeroes.
# An amount such as 5,000 or 20.000 must never imply a thousands scale.
QUOTED_THOUSANDS = r"(?:(?<!\d)['’`]\s*000(?!\d)|(?<![\d.,])000\s*['’`](?!\d))"
