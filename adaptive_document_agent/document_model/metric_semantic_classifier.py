"""Metric semantic classification and investor-presentation formatting."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class MetricSemantic:
    metric_type: str  # 'currency', 'percentage', 'multiple', 'days', 'count', 'generic'
    clean_name: str
    display_unit: str
    is_currency: bool
    is_percentage: bool


# Canonical keywords for metric classification
_PERCENTAGE_KEYWORDS = (
    "margin",
    "share of revenue",
    "% of revenue",
    "as % of revenue",
    "revenue share",
    "expense ratio",
    "growth rate",
    "cagr",
    "rate",
    "percentage",
    "pct",
    "ratio",
    "proportion",
    "market share",
    "effective tax rate",
)

_CURRENCY_KEYWORDS = (
    "revenue",
    "gross profit",
    "operating profit",
    "operating loss",
    "loss from operations",
    "profit from operations",
    "loss for the year",
    "profit for the year",
    "net profit",
    "net loss",
    "adjusted ebitda",
    "ebitda",
    "ebit",
    "cost of sales",
    "cost of revenue",
    "cash and cash equivalents",
    "cash balance",
    "bank balances",
    "borrowings",
    "liabilities",
    "redemption liabilities",
    "net current liabilities",
    "trade receivables",
    "trade payables",
    "inventories",
    "total assets",
    "total equity",
    "capital expenditure",
    "capex",
)

_DAYS_KEYWORDS = (
    "turnover days",
    "days sales outstanding",
    "dso",
    "days inventory outstanding",
    "dio",
    "days payable outstanding",
    "dpo",
    "days",
)

_MULTIPLE_KEYWORDS = (
    "multiple",
    "quick ratio",
    "current ratio",
    "debt-to-equity",
    "leverage ratio",
    "times",
)


def classify_metric(
    name: str,
    *,
    value: float | None = None,
    raw_unit: str | None = None,
    unit: str | None = None,
) -> MetricSemantic:
    clean = sanitize_metric_label(name)
    lower = clean.casefold()

    # Days metric
    if any(k in lower for k in _DAYS_KEYWORDS):
        return MetricSemantic(
            metric_type="days",
            clean_name=clean,
            display_unit="days",
            is_currency=False,
            is_percentage=False,
        )

    # Multiples
    if any(k in lower for k in _MULTIPLE_KEYWORDS) and not any(k in lower for k in ("days", "%")):
        return MetricSemantic(
            metric_type="multiple",
            clean_name=clean,
            display_unit="x",
            is_currency=False,
            is_percentage=False,
        )

    # Explicit margin or percentage keyword
    if any(k in lower for k in _PERCENTAGE_KEYWORDS) and not any(
        k in lower for k in ("gross profit:", "gross profit (", "revenue:", "net loss:")
    ):
        return MetricSemantic(
            metric_type="percentage",
            clean_name=clean,
            display_unit="%",
            is_currency=False,
            is_percentage=True,
        )

    # Explicit currency metric (e.g. Gross profit, Revenue, Adjusted EBITDA, Loss for the year)
    if any(k in lower for k in _CURRENCY_KEYWORDS):
        # Check if this is explicitly a margin/ratio of that currency metric
        if "margin" in lower or "ratio" in lower or "share" in lower or "%" in lower:
            return MetricSemantic(
                metric_type="percentage",
                clean_name=clean,
                display_unit="%",
                is_currency=False,
                is_percentage=True,
            )
        return MetricSemantic(
            metric_type="currency",
            clean_name=clean,
            display_unit=raw_unit or "currency",
            is_currency=True,
            is_percentage=False,
        )

    # Fallback to unit hint
    if unit == "percent" or (raw_unit and "%" in raw_unit):
        return MetricSemantic(
            metric_type="percentage",
            clean_name=clean,
            display_unit="%",
            is_currency=False,
            is_percentage=True,
        )
    elif unit == "currency":
        return MetricSemantic(
            metric_type="currency",
            clean_name=clean,
            display_unit=raw_unit or "currency",
            is_currency=True,
            is_percentage=False,
        )

    return MetricSemantic(
        metric_type="generic",
        clean_name=clean,
        display_unit=raw_unit or "",
        is_currency=False,
        is_percentage=False,
    )


def is_currency_metric(name: str) -> bool:
    return classify_metric(name).is_currency


def is_percentage_metric(name: str) -> bool:
    return classify_metric(name).is_percentage


def sanitize_metric_label(name: str) -> str:
    clean = " ".join(name.strip().split())
    # Remove nonsensical '% of RMB' or similar
    clean = re.sub(r"(?i)\s*%\s*of\s*rmb\b", "", clean).strip()
    clean = re.sub(r"(?i)\s*%\s*of\s*(?:usd|cny|hkd|eur)\b", "", clean).strip()
    clean = re.sub(r"^[:\-\s]+|[:\-\s]+$", "", clean).strip()
    if not clean:
        clean = "Reported metric"

    # Normalize expense ratio titles before segment shares
    if re.search(r"(?i)research(?:\s+and\s+|\s*&\s*)development(?:\s+expenses?)?\s+(?:as\s+)?(?:%|ratio)\s+(?:of\s+)?revenue", clean):
        clean = "R&D / revenue"
    elif re.search(r"(?i)research(?:\s+and\s+|\s*&\s*)development(?:\s+expense)?$", clean) and "ratio" in clean.casefold():
        clean = "R&D / revenue"

    # Normalize segment shares
    clean = re.sub(r"(?i)\s*%\s*of\s*total\s*revenue$", " share of revenue", clean)
    clean = re.sub(r"(?i)\s*%\s*of\s*revenue$", " share of revenue", clean)

    # If it says 'Warehouse fulfillment revenue' but context is share of revenue, format clearly
    if re.search(r"(?i)warehouse fulfillment(?:\s+solutions)?\s+revenue$", clean):
        clean = "Warehouse fulfillment share of revenue"

    return clean
