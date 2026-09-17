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
) -> str:
    """Format currency values into compact financial notation (e.g. 'RMB 174.3m', 'RMB 1.57bn', 'RMB 450k').

    Handles both already-scaled amounts (e.g. 174,314,000.0) and unscaled thousands figures.
    """
    curr = normalize_currency_symbol(currency)

    # Detect if scale factor needs to be applied
    val = float(amount)
    if unit_scale and unit_scale > 1.0 and abs(val) < 100_000_000:
        val = val * unit_scale
    elif raw_unit and any(term in raw_unit.lower() for term in ("thousand", "'000", "inthousands")) and abs(val) < 100_000_000:
        val = val * 1000.0

    is_negative = val < 0
    abs_val = abs(val)

    if abs_val >= 1_000_000_000:
        scaled = abs_val / 1_000_000_000.0
        # If integer or single decimal, format cleanly
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
    clean = " ".join(name.strip().split())

    # Map expense ratios
    if re.search(r"(?i)cost\s+of\s+(?:sales|revenue)\s*(?::\s*share\s+of\s+revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio)", clean):
        return "Cost of Sales / Revenue"
    if re.search(r"(?i)selling\s+(?:and|&)\s+distribution(?:\s+expenses?)?\s*(?::\s*share\s+of\s+revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio)", clean):
        return "Selling & Distribution / Revenue"
    if re.search(r"(?i)administrative\s+expenses?\s*(?::\s*share\s+of\s+revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio)", clean):
        return "Admin / Revenue"
    if re.search(r"(?i)research\s+(?:and|&)\s+development(?:\s+expenses?)?\s*(?::\s*share\s+of\s+revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio)", clean):
        return "R&D / Revenue"

    # Map balance sheet items
    if re.search(r"(?i)\bcash\s+and\s+cash\s+equivalents\b", clean):
        return "Cash & Cash Equivalents"
    if re.search(r"(?i)\btrade\s+and\s+(?:bills\s+)?receivables\b", clean):
        return "Trade Receivables"
    if re.search(r"(?i)\btrade\s+and\s+(?:bills\s+)?payables\b", clean):
        return "Trade Payables"
    if re.search(r"(?i)\bgross\s+profit\s+margin\b", clean):
        return "Gross Margin"
    if re.search(r"(?i)\boperating\s+profit\s+margin\b", clean):
        return "Operating Margin"
    if re.search(r"(?i)\bnet\s+profit\s+margin\b", clean):
        return "Net Margin"
    if re.search(r"(?i)\bcontract\s+liabilities\b", clean):
        return "Contract Liabilities"
    if re.search(r"(?i)\bgearing\s+ratio\b", clean):
        return "Gearing Ratio"
    if re.search(r"(?i)\bcurrent\s+ratio\b", clean):
        return "Current Ratio"
    if re.search(r"(?i)\bquick\s+ratio\b", clean):
        return "Quick Ratio"

    # Remove verbose prefixes/suffixes
    clean = re.sub(r"(?i)^the\s+group'?s?\s+", "", clean)
    clean = re.sub(r"(?i)\s+for\s+the\s+year$", "", clean)
    clean = re.sub(r"(?i)\s+for\s+the\s+period$", "", clean)
    return clean


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
    """Generate standard institutional financial phrasing for analytical movements.

    - Expense ratios: 'Cost of sales ratio increased by 6.6 pp' (never 'Loss widened')
    - Margins: 'Gross margin expanded by 3.2 pp' or 'contracted by 1.5 pp'
    - Multiples: '+0.20x'
    - Liabilities: 'Liability widened by RMB 50m' or 'narrowed by RMB 20m'
    - Losses: 'Loss narrowed from RMB 683m to RMB 25m'
    """
    clean_title = shorten_metric_title(metric_name)
    lower = clean_title.casefold()

    is_exp_ratio = is_expense_ratio_metric(clean_title)
    is_margin = "margin" in lower or "毛利" in lower or "净利" in lower
    is_liab = any(k in lower for k in _LIABILITY_KEYWORDS)
    is_loss = "loss" in lower or "亏损" in lower or (start_val < 0 and end_val < 0)

    # 1. Expense Ratios (e.g. Cost of sales / revenue, Selling / revenue)
    if is_exp_ratio:
        # Normalize accounting negative values to positive intensity
        s = abs(start_val)
        e = abs(end_val)
        diff = e - s
        direction = "increased" if diff >= 0 else "decreased"
        return f"{clean_title} {direction} by {abs(diff):.1f} pp"

    # 2. Margins (Gross Margin, Operating Margin, Net Margin)
    if is_margin or (unit_family == "percentage" and not is_loss):
        diff = end_val - start_val
        direction = "expanded" if diff >= 0 else "contracted"
        return f"{clean_title} {direction} by {abs(diff):.1f} pp"

    # 3. Multiples (Current ratio, Quick ratio, Gearing)
    if unit_family == "multiple" or "ratio" in lower:
        diff = end_val - start_val
        return f"{diff:+.2f}x"

    # 4. Turnaround (Negative to Positive or vice versa)
    if start_val < 0 <= end_val:
        return "Turned profitable" if "profit" in lower or "loss" in lower else "Turned positive"
    if start_val > 0 >= end_val:
        return "Turned loss-making" if "profit" in lower or "loss" in lower else "Turned negative"

    # 5. Losses (Both negative)
    if is_loss or (start_val < 0 and end_val < 0):
        s_abs = abs(start_val)
        e_abs = abs(end_val)
        start_fmt = format_compact_currency(s_abs, currency=currency, unit_scale=scale)
        end_fmt = format_compact_currency(e_abs, currency=currency, unit_scale=scale)
        if e_abs < s_abs:
            return f"Loss narrowed from {start_fmt} to {end_fmt}"
        return f"Loss widened from {start_fmt} to {end_fmt}"

    # 6. Liabilities / Indebtedness
    if is_liab and start_val > 0 and end_val > 0:
        diff_abs = abs(end_val - start_val)
        diff_fmt = format_compact_currency(diff_abs, currency=currency, unit_scale=scale)
        action = "widened" if end_val > start_val else "narrowed"
        return f"Liability {action} by {diff_fmt}"

    # 7. Standard currency growth rate
    if start_val != 0:
        pct_change = ((end_val - start_val) / abs(start_val)) * 100.0
        return f"{pct_change:+.1f}%"

    diff_val = end_val - start_val
    return format_compact_currency(diff_val, currency=currency, unit_scale=scale)
