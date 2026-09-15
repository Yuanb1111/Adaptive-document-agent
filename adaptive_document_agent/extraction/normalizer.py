"""Unit compatibility, source-unit detection, and scale normalisation."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UnitSignature:
    unit: str | None
    currency: str | None = None


@dataclass(frozen=True)
class UnitDefaults:
    """A table-level unit declaration preserved separately from raw values."""

    unit: str | None = None
    scale: float | None = None
    currency: str | None = None
    raw_unit: str | None = None


_CURRENCIES: tuple[tuple[str, str], ...] = (
    (r"\b(?:rmb|cny)(?=\b|in(?:thousands?|millions?|billions?)|['’`]0{3})|人民币", "CNY"),
    (r"hk\s*\$|\bhkd\b|港元", "HKD"),
    (r"us\s*\$|\busd\b", "USD"),
    (r"\bsgd\b|s\s*\$", "SGD"),
    (r"\beur\b|€", "EUR"),
    (r"\bgbp\b|£", "GBP"),
)

_SCALES: tuple[tuple[str, float], ...] = (
    (r"billions?|bn\b|十亿", 1_000_000_000.0),
    (r"millions?|mn\b|百万", 1_000_000.0),
    (r"thousands?|['’`]\s*0{3}\b|千元", 1_000.0),
)


def infer_unit_defaults(text: str) -> UnitDefaults:
    """Infer only explicit currency/scale declarations from nearby table text.

    The source phrase is retained so presentation never has to reconstruct or
    guess whether a reported number was stated in units, thousands, or millions.
    """
    compact = " ".join(text.split())
    lowered = compact.casefold()
    declaration_pattern = re.compile(
        r"(?i)(?P<currency>rmb|cny|hk\s*\$|hkd|us\s*\$|usd|sgd|s\s*\$|eur|gbp|人民币|港元)"
        r"\s*(?:in\s*)?(?P<scale>['’`]\s*0{3}|thousands?|millions?|billions?|千元|百万|十亿)"
    )
    declarations = list(declaration_pattern.finditer(compact))
    declaration_match = declarations[-1] if declarations else None
    declaration = declaration_match.group(0).strip() if declaration_match else None
    currency = next((code for pattern, code in _CURRENCIES if re.search(pattern, declaration or lowered, re.I)), None)
    scale_text = declaration_match.group("scale").casefold() if declaration_match else lowered
    scale = next((amount for pattern, amount in _SCALES if re.search(pattern, scale_text, re.I)), None)
    percent = bool(re.search(r"%|percent(?:age)?s?", lowered))
    unit = "currency" if currency else "percent" if percent else None

    if currency and not declaration:
        currency_match = next((re.search(pattern, compact, re.I) for pattern, _ in _CURRENCIES if re.search(pattern, compact, re.I)), None)
        declaration = currency_match.group(0).strip() if currency_match else None
    if scale and not declaration:
        scale_match = re.search(r"(?i)(?:in\s+)?(?:thousands?|millions?|billions?|['’`]\s*0{3}|千元|百万|十亿)", compact)
        declaration = scale_match.group(0).strip() if scale_match else None
    return UnitDefaults(unit=unit, scale=scale, currency=currency, raw_unit=declaration)


def compatible_units(left: UnitSignature, right: UnitSignature) -> bool:
    if left.currency or right.currency:
        return left.currency == right.currency and left.unit == right.unit
    return left.unit == right.unit or (left.unit is None and right.unit is None)


def ratio_unit(numerator: UnitSignature, denominator: UnitSignature) -> str | None:
    if compatible_units(numerator, denominator):
        return "ratio"
    return None
