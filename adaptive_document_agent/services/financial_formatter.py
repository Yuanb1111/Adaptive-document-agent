"""Standardized financial number formatting, unit normalization, and investor phrasing.

Zero hardcoding: all rules operate on semantic types, unit families, and standard accounting patterns.
"""

from __future__ import annotations

import math
import re
from typing import Any

# Canonical currency symbols / abbreviations for client presentation
_CURRENCY_SYMBOLS: dict[str, str] = {
    "CNY": "RMB",
    "RMB": "RMB",
    "HKD": "HK$",
    "HK$": "HK$",
    "USD": "US$",
    "US$": "US$",
    "EUR": "€",
    "GBP": "£",
    "SGD": "S$",
    "S$": "S$",
    "JPY": "¥",
    "AUD": "A$",
}

# Expense ratio keywords where accounting disclosures may use negative numbers or loss terminology
_EXPENSE_RATIO_KEYWORDS = (
    "cost of sales",
    "cost of revenue",
    "selling and distribution",
    "selling expense",
    "administrative expense",
    "admin expense",
    "research and development",
    "r&d",
    "finance cost",
    "operating expense",
    "expense ratio",
    "share of revenue",
    "/ revenue",
    "销售成本",
    "营业成本",
    "研发费用",
    "研发开支",
    "销售费用",
    "管理费用",
)

# Liability / debt keywords for widen/narrow phrasing
_LIABILITY_KEYWORDS = (
    "liabilit",
    "borrowing",
    "debt",
    "indebtedness",
    "deficit",
    "loan",
    "负债",
    "借款",
    "借贷",
    "赤字",
)


def normalize_currency_symbol(currency: str | None) -> str:
    """Map raw currency string to standardized presentation code/symbol."""
    if not currency:
        return "RMB"
    clean = currency.strip().upper()
    return _CURRENCY_SYMBOLS.get(clean, clean)


def normalize_raw_unit(raw_unit: str | None, *, default_currency: str = "RMB") -> str:
    """Normalize raw or corrupted unit tokens into institutional-grade presentation strings.

    Bans internal unspaced tokens like 'RMBinthousands', 'cnymillions', 'RMB'000'.
    """
    if not raw_unit:
        return ""

    text = raw_unit.strip()
    # Normalize unicode quotes and non-breaking spaces
    text = re.sub(r"[\u2018\u2019\u0060\ufffd]", "'", text)
    text = " ".join(text.split())

    lower = text.casefold()

    # Multiples
    if lower in {"x", "times", "multiple", "倍"}:
        return "x"

    # Percentage / Shares
    if "%" in text or lower in {"percent", "percentage", "pct", "in percent", "百分比"}:
        return "%"

    # Days
    if "day" in lower or "天" in lower:
        return "days"

    # Count / Volume
    if lower in {"units", "count", "sets", "pieces", "pcs", "heads", "台", "件", "个", "套"}:
        return "units"

    # Currency extraction
    curr_match = re.search(r"(?i)(?:rmb|cny|hk\s*\$|hkd|us\s*\$|usd|eur|gbp|sgd|s\s*\$|人民币|港元)", text)
    curr_str = normalize_currency_symbol(curr_match.group(0)) if curr_match else normalize_currency_symbol(default_currency)

    # Scale extraction
    if re.search(r"(?i)(?:billions?|bn|十亿)", text):
        return f"{curr_str} billion"
    if re.search(r"(?i)(?:millions?|mn|百万)", text):
        return f"{curr_str} million"
    if re.search(r"(?i)(?:thousands?|['’`]\s*000|千元|inthousands)", text):
        return f"{curr_str} '000"

    # Generic cleanup: separate concatenated words like "RMBinthousands"
    cleaned = re.sub(r"(?i)\b(rmb|cny|hkd|usd)(?:in)?(thousands?|'000)\b", r"\1 '000", text)
    cleaned = re.sub(r"(?i)\b(rmb|cny|hkd|usd)(?:in)?(millions?)\b", r"\1 million", cleaned)
    cleaned = re.sub(r"(?i)\b(rmb|cny|hkd|usd)(?:in)?(billions?)\b", r"\1 billion", cleaned)
    cleaned = re.sub(r"(?i)%\s*of\s*rmb", "RMB '000", cleaned)
    return cleaned


def format_compact_currency(
    amount: float,
    *,
    raw_unit: str | None = None,
    currency: str | None = "RMB",
    unit_scale: float | None = None,
    is_base_value: bool | None = None,
) -> str:
    """Format currency values into compact financial notation (e.g. 'RMB 174.3m', 'RMB 1.57bn', 'RMB 450k').

    Handles both already-scaled base amounts (e.g. 174,314,000.0) and unscaled thousands figures.
    """
    curr = normalize_currency_symbol(currency)
    val = float(amount)

    if is_base_value is True:
        # Value is already in base currency units: do not multiply by scale
        pass
    elif is_base_value is False:
        if unit_scale and unit_scale > 1.0:
            val = val * unit_scale
        elif raw_unit and any(term in raw_unit.lower() for term in ("thousand", "'000", "inthousands")):
            val = val * 1000.0
        elif raw_unit and any(term in raw_unit.lower() for term in ("billion", "bn", "十亿")):
            val = val * 1_000_000_000.0
        elif raw_unit and any(term in raw_unit.lower() for term in ("million", "mn", "百万")):
            val = val * 1_000_000.0
    else:
        # Backward-compatible auto-detection for standalone unscaled numbers passed without flag
        if unit_scale and unit_scale > 1.0 and abs(val) < 20_000_000:
            val = val * unit_scale
        elif raw_unit and any(term in raw_unit.lower() for term in ("thousand", "'000", "inthousands")) and abs(val) < 20_000_000:
            val = val * 1000.0

    is_negative = val < 0
    abs_val = abs(val)

    if abs_val >= 1_000_000_000:
        scaled = abs_val / 1_000_000_000.0
        formatted = f"{curr} {scaled:.2f}bn" if scaled < 10 else f"{curr} {scaled:.1f}bn"
    elif abs_val >= 1_000_000:
        scaled = abs_val / 1_000_000.0
        if scaled == int(scaled):
            formatted = f"{curr} {int(scaled)}m"
        else:
            formatted = f"{curr} {scaled:.1f}m"
    elif abs_val >= 1_000:
        scaled = abs_val / 1_000.0
        formatted = f"{curr} {scaled:.0f}k"
    else:
        formatted = f"{curr} {abs_val:,.0f}"

    return f"-{formatted}" if is_negative else formatted


def shorten_metric_title(name: str) -> str:
    """Shorten verbose accounting lines for KPI cards and chart titles."""
    from adaptive_document_agent.services.language_qa import clean_metric_label

    return clean_metric_label(name)


def is_expense_ratio_metric(name: str) -> bool:
    """Check if metric represents an expense ratio where positive indicates cost intensity."""
    lower = name.casefold()
    return any(k in lower for k in _EXPENSE_RATIO_KEYWORDS) and any(
        s in lower for s in ("ratio", "share", "%", "margin", "/ revenue", "比例", "占比")
    )


def format_financial_movement(
    metric_name: str,
    start_val: float,
    end_val: float,
    *,
    unit_family: str = "generic",
    scale: float = 1.0,
    currency: str = "RMB",
) -> str:
    """Generate standard institutional financial phrasing for analytical movements using FinancialMovementFormatter."""
    from adaptive_document_agent.services.movement_formatter import FinancialMovementFormatter

    return FinancialMovementFormatter.format_movement(
        metric_name,
        start_val,
        end_val,
        currency=currency,
        scale=scale,
        unit_family=unit_family,
        include_metric_name=True,
    )

