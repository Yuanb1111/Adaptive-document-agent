"""Locale-tolerant numeric parsing that always preserves the raw value."""

import re
from math import isfinite

from pydantic import BaseModel


class ParsedNumber(BaseModel):
    raw_value: str
    value: float
    raw_unit: str | None = None
    unit: str | None = None
    scale: float = 1.0
    currency: str | None = None
    confidence: float = 1.0


_CURRENCIES = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "HK$": "HKD",
    "HKD": "HKD",
    "£": "GBP",
    "GBP": "GBP",
    "€": "EUR",
    "EUR": "EUR",
    "¥": "CNY",
    "CNY": "CNY",
    "RMB": "CNY",
    "SGD": "SGD",
    "S$": "SGD",
}
_SCALES = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "mn": 1_000_000.0,
    "million": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
}


def parse_number(raw: str | int | float) -> ParsedNumber | None:
    original = str(raw).strip()
    if not original or original.casefold() in {"n/a", "na", "—", "-", "nil", "none"}:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return ParsedNumber(raw_value=original, value=value) if isfinite(value) else None

    text = original.replace("\u00a0", " ").replace("％", "%").strip()
    negative = (text.startswith("(") and text.endswith(")")) or text.endswith("-")
    if negative:
        text = text[1:-1] if text.startswith("(") else text[:-1]
    currency = None
    currency_match = re.search(r"(?i)(US\$|USD|SGD|S\$|GBP|EUR|CNY|RMB|HK\$|HKD|[$£€¥])", text)
    if currency_match:
        curr_key = currency_match.group(1).upper()
        currency = _CURRENCIES.get(curr_key, _CURRENCIES.get(currency_match.group(1)))
        text = text[: currency_match.start()] + text[currency_match.end() :]

    unit = None
    raw_unit = None
    scale = 1.0
    if re.search(r"(?i)\bbps?\b|basis\s+points?", text):
        unit, raw_unit = "basis_points", "bps"
        text = re.sub(r"(?i)\bbps?\b|basis\s+points?", "", text)
    elif re.search(r"(?i)\bpp\b|percentage\s+points?", text):
        unit, raw_unit = "percentage_points", "pp"
        text = re.sub(r"(?i)\bpp\b|percentage\s+points?", "", text)
    elif "%" in text or re.search(r"(?i)\bpercent(?:age)?\b", text):
        unit, raw_unit = "percent", "%"
        text = re.sub(r"(?i)%|\bpercent(?:age)?\b", "", text)
    elif re.search(r"(?i)(?<=\d)\s*(?:x|times|倍)\b", text):
        unit, raw_unit = "multiple", "x"
        text = re.sub(r"(?i)\s*(?:x|times|倍)\b", "", text)

    scale_match = re.search(r"(?i)(?:\s|(?<=\d))(thousand|million|billion|bn|mn|[kmb])\b", text)
    if scale_match:
        raw_scale = scale_match.group(1)
        scale = _SCALES[raw_scale.casefold()]
        raw_unit = " ".join(part for part in [raw_unit, raw_scale] if part)
        text = text[: scale_match.start()] + text[scale_match.end() :]

    # Unit suffixes may sit outside accounting parentheses: '(12.5)%'.
    # Strip them first, then recognise the remaining parenthesised number.
    text = text.strip()
    if not negative and text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    cleaned = text.strip().replace(",", "")
    cleaned = re.sub(r"(?<=\d)\s+(?=\d{3}(?:\D|$))", "", cleaned)
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", cleaned):
        return None
    value = float(cleaned) * scale
    if negative and value > 0:
        value = -value
    if not isfinite(value):
        return None
    return ParsedNumber(
        raw_value=original,
        value=value,
        raw_unit=raw_unit,
        unit=unit or ("currency" if currency else None),
        scale=scale,
        currency=currency,
        confidence=0.95 if scale_match or currency_match else 1.0,
    )
