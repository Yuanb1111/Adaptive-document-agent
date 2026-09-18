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
    curr_first_pattern = re.compile(
        r"(?i)(?P<currency>rmb|cny|hk\s*\$|hkd|us\s*\$|usd|sgd|s\s*\$|eur|gbp|人民币|港元)"
        r"\s*(?:in\s*)?(?P<scale>['’`]\s*0{3}|thousands?|millions?|billions?|千元|百万|十亿)"
    )
    scale_first_pattern = re.compile(
        r"(?i)(?:in\s+)?(?P<scale>['’`]\s*0{3}|thousands?|millions?|billions?|千元|百万|十亿)"
        r"\s*(?:of\s+)?(?P<currency>rmb|cny|hk\s*\$|hkd|us\s*\$|usd|sgd|s\s*\$|eur|gbp|人民币|港元)"
    )
    declarations = list(curr_first_pattern.finditer(compact)) or list(scale_first_pattern.finditer(compact))
    declaration_match = declarations[-1] if declarations else None
    declaration = declaration_match.group(0).strip() if declaration_match else None
    currency = next((code for pattern, code in _CURRENCIES if re.search(pattern, declaration or lowered, re.I)), None)
    scale_text = declaration_match.group("scale").casefold() if declaration_match else lowered
    scale = next((amount for pattern, amount in _SCALES if re.search(pattern, scale_text, re.I)), None)
    percent_declaration = bool(re.search(r"(?i)\b(?:in\s+%)|(?:in\s+percent(?:age)?s?)\b|\((?:%|percent)\)", compact))
    unit = "currency" if currency else "percent" if percent_declaration else None

    if currency and not declaration:
        currency_match = next((re.search(pattern, compact, re.I) for pattern, _ in _CURRENCIES if re.search(pattern, compact, re.I)), None)
        declaration = currency_match.group(0).strip() if currency_match else None
    if declaration:
        declaration = re.sub(r"(?i)\b(rmb|cny|hkd|hk\s*\$|usd|us\s*\$|eur|gbp)(?:in)?(thousands?|'000)\b", r"\1 in thousands", declaration)
        declaration = re.sub(r"(?i)\b(rmb|cny|hkd|hk\s*\$|usd|us\s*\$|eur|gbp)(?:in)?(millions?)\b", r"\1 in millions", declaration)
        declaration = re.sub(r"(?i)\b(rmb|cny|hkd|hk\s*\$|usd|us\s*\$|eur|gbp)(?:in)?(billions?)\b", r"\1 in billions", declaration)
    return UnitDefaults(unit=unit, scale=scale, currency=currency, raw_unit=declaration)


def normalize_financial_fact(
    raw_value: str | int | float,
    raw_unit: str | None = None,
    *,
    default_currency: str | None = None,
    default_scale: float = 1.0,
) -> tuple[float | None, str | None, str, str, str | None]:
    """Deterministically convert raw numeric string and unit declarations into:
    (normalized_value, normalized_unit, display_value, display_unit, currency).

    Never guesses or uses LLM reasoning for numerical conversions.
    """
    from .numeric_parser import parse_number
    from adaptive_document_agent.services.financial_formatter import (
        format_compact_currency,
        normalize_currency_symbol,
    )

    parsed = parse_number(raw_value)
    if not parsed:
        return None, None, str(raw_value), "", default_currency

    scale = parsed.scale
    currency = parsed.currency or default_currency
    unit = parsed.unit

    if raw_unit:
        inferred = infer_unit_defaults(raw_unit)
        if inferred.scale and scale == 1.0:
            scale = inferred.scale
        if inferred.currency and not currency:
            currency = inferred.currency
        if inferred.unit and not unit:
            unit = inferred.unit

    if not scale or scale <= 0:
        scale = default_scale

    normalized_value = parsed.value * scale if scale != 1.0 and parsed.scale == 1.0 else parsed.value
    curr_sym = normalize_currency_symbol(currency)

    if unit == "percent" or (parsed.raw_unit and "%" in parsed.raw_unit):
        normalized_unit = "percent"
        display_unit = "%"
        display_value = f"{parsed.value:g}%"
    elif unit == "percentage_points" or (parsed.raw_unit and "pp" in parsed.raw_unit.lower()):
        normalized_unit = "percentage_points"
        display_unit = "pp"
        display_value = f"{parsed.value:g} pp"
    elif unit == "basis_points" or (parsed.raw_unit and "bps" in parsed.raw_unit.lower()):
        normalized_unit = "basis_points"
        display_unit = "bps"
        display_value = f"{parsed.value:g} bps"
    elif unit == "multiple" or (parsed.raw_unit and "x" in parsed.raw_unit.lower()):
        normalized_unit = "multiple"
        display_unit = "x"
        display_value = f"{parsed.value:g}x"
    elif currency or unit == "currency":
        normalized_unit = "currency"
        display_value = format_compact_currency(normalized_value, currency=currency, is_base_value=True)
        abs_norm = abs(normalized_value)
        if abs_norm >= 1_000_000_000:
            display_unit = f"{curr_sym} billion"
        elif abs_norm >= 1_000_000:
            display_unit = f"{curr_sym} million"
        elif abs_norm >= 1_000:
            display_unit = f"{curr_sym} '000"
        else:
            display_unit = curr_sym
    else:
        normalized_unit = unit or "generic"
        display_unit = parsed.raw_unit or raw_unit or ""
        display_value = str(raw_value)

    return normalized_value, normalized_unit, display_value, display_unit, currency


def compatible_units(left: UnitSignature, right: UnitSignature) -> bool:
    if left.currency or right.currency:
        return left.currency == right.currency and left.unit == right.unit
    return left.unit == right.unit or (left.unit is None and right.unit is None)


def ratio_unit(numerator: UnitSignature, denominator: UnitSignature) -> str | None:
    if compatible_units(numerator, denominator):
        return "ratio"
    return None
