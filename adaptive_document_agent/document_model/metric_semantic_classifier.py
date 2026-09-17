"""Metric semantic classification, unit typing, and investor-presentation formatting."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


from adaptive_document_agent.services.financial_formatter import (
    format_compact_currency,
    is_expense_ratio_metric,
    normalize_raw_unit,
    shorten_metric_title,
)


@dataclass(frozen=True)
class MetricSemantic:
    metric_type: str  # 'currency', 'percentage', 'multiple', 'days', 'count', 'generic'
    unit_family: str  # 'currency', 'percentage', 'multiple', 'days', 'count', 'generic'
    semantic_type: str  # 'monetary_amount', 'margin', 'ratio_share', 'multiple', 'days', 'count', 'growth_rate', 'generic'
    clean_name: str
    display_unit: str
    is_currency: bool
    is_percentage: bool
    is_multiple: bool
    is_expense_ratio: bool = False
    is_volume: bool = False
    short_display_name: str = ""


# Canonical keywords for metric classification
_MULTIPLE_KEYWORDS = (
    "current ratio",
    "quick ratio",
    "cash ratio",
    "gearing ratio (multiple)",
    "net debt to ebitda",
    "debt to equity ratio (multiple)",
    "asset turnover",
    "inventory turnover ratio",
    "receivables turnover ratio",
    "multiple",
    "times",
    "流动比率",
    "速动比率",
    "现金比率",
)

_MARGIN_KEYWORDS = (
    "gross margin",
    "gross profit margin",
    "operating margin",
    "operating profit margin",
    "net margin",
    "net profit margin",
    "ebitda margin",
    "adjusted ebitda margin",
    "effective tax rate",
    "gearing ratio",
    "毛利率",
    "净利率",
    "净利润率",
    "营业利润率",
    "经营利润率",
    "ebitda利润率",
    "资产负债率",
)

_SHARE_KEYWORDS = (
    "share of revenue",
    "% of revenue",
    "as % of revenue",
    "as a percentage of revenue",
    "revenue share",
    "expense ratio",
    "% of total",
    "share of total",
    "market share",
    "/ revenue",
    "占收入比例",
    "占营业收入比例",
    "占总额比例",
    "占比",
)

_PERCENTAGE_OTHER_KEYWORDS = (
    "growth rate",
    "cagr",
    "percentage",
    "pct",
    "proportion",
    "增长率",
    "同比",
    "复合年增长率",
    "百分比",
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
    "selling and distribution expenses",
    "administrative expenses",
    "research and development expenses",
    "r&d expenses",
    "finance costs",
    "income tax expense",
    "cash and cash equivalents",
    "cash balance",
    "bank balances",
    "borrowings",
    "liabilities",
    "redemption liabilities",
    "net current liabilities",
    "net current assets",
    "trade receivables",
    "trade payables",
    "inventories",
    "total assets",
    "total equity",
    "capital expenditure",
    "capex",
    "营业收入",
    "主营业务收入",
    "毛利",
    "毛利润",
    "营业利润",
    "经营利润",
    "营业亏损",
    "经营亏损",
    "净利润",
    "净亏损",
    "年内亏损",
    "年内利润",
    "期内亏损",
    "期内利润",
    "销售成本",
    "营业成本",
    "研发开支",
    "研发费用",
    "行政开支",
    "管理费用",
    "销售及分销开支",
    "销售费用",
    "财务成本",
    "所得税开支",
    "所得税费用",
    "现金及现金等价物",
    "银行结余及现金",
    "借贷",
    "银行借款",
    "贸易应收款项",
    "应收账款",
    "贸易应付款项",
    "应付账款",
    "存货",
    "流动资产",
    "流动负债",
    "资产总值",
    "总资产",
    "负债总额",
    "总负债",
    "权益总额",
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

_VOLUME_KEYWORDS = (
    "volume",
    "sales volume",
    "shipment",
    "units sold",
    "quantity",
    "number of units",
    "fleet size",
    "heads",
    "sets",
    "pieces",
    "pcs",
    "销量",
    "销售量",
    "出货量",
    "数量",
    "台",
    "件",
    "套",
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
    short_title = shorten_metric_title(clean)

    # 1. Multiples / Ratios (Current ratio, Quick ratio, etc.)
    # Must precede percentage and currency checks to prevent ratios from being misclassified as percent.
    if any(k in lower for k in _MULTIPLE_KEYWORDS) and not any(k in lower for k in ("days", "% of", "share of")):
        return MetricSemantic(
            metric_type="multiple",
            unit_family="multiple",
            semantic_type="multiple",
            clean_name=clean,
            display_unit="x",
            is_currency=False,
            is_percentage=False,
            is_multiple=True,
            short_display_name=short_title,
        )

    # 2. Days metrics (Turnover days, DSO, DIO, DPO)
    if any(k in lower for k in _DAYS_KEYWORDS):
        return MetricSemantic(
            metric_type="days",
            unit_family="days",
            semantic_type="days",
            clean_name=clean,
            display_unit="days",
            is_currency=False,
            is_percentage=False,
            is_multiple=False,
            short_display_name=short_title,
        )

    # 3. Volume / Count metrics (Units sold, Sales volume, Shipment)
    is_asp = any(asp in lower for asp in ("average selling price", "asp", "unit price", "price per", "单价", "平均售价"))
    if any(k in lower for k in _VOLUME_KEYWORDS) and not is_asp and not any(k in lower for k in ("share", "%", "margin", "ratio", "revenue", "cost")):
        return MetricSemantic(
            metric_type="count",
            unit_family="count",
            semantic_type="count",
            clean_name=clean,
            display_unit="units",
            is_currency=False,
            is_percentage=False,
            is_multiple=False,
            is_expense_ratio=False,
            is_volume=True,
            short_display_name=short_title,
        )

    # 4. Explicit Share of revenue / expense ratio
    is_exp = is_expense_ratio_metric(clean)
    if any(k in lower for k in _SHARE_KEYWORDS) or lower.endswith("/ revenue") or is_exp:
        return MetricSemantic(
            metric_type="percentage",
            unit_family="percentage",
            semantic_type="ratio_share",
            clean_name=clean,
            display_unit="%",
            is_currency=False,
            is_percentage=True,
            is_multiple=False,
            is_expense_ratio=is_exp,
            short_display_name=short_title,
        )

    # 5. Explicit Margin metrics (Gross margin, Operating margin, etc.)
    if any(k in lower for k in _MARGIN_KEYWORDS):
        return MetricSemantic(
            metric_type="percentage",
            unit_family="percentage",
            semantic_type="margin",
            clean_name=clean,
            display_unit="%",
            is_currency=False,
            is_percentage=True,
            is_multiple=False,
            short_display_name=short_title,
        )

    # 5. Currency line items (Revenue, Gross profit, Loss from operations, Cash, Liabilities, etc.)
    # Protect absolute financial amounts from spurious '%' unit hints.
    if any(k in lower for k in _CURRENCY_KEYWORDS):
        # Check if this is explicitly a share or margin sub-metric
        if "share" in lower or "%" in lower or "margin" in lower or "/ revenue" in lower:
            return MetricSemantic(
                metric_type="percentage",
                unit_family="percentage",
                semantic_type="ratio_share",
                clean_name=clean,
                display_unit="%",
                is_currency=False,
                is_percentage=True,
                is_multiple=False,
                is_expense_ratio=is_exp,
                short_display_name=short_title,
            )
        return MetricSemantic(
            metric_type="currency",
            unit_family="currency",
            semantic_type="monetary_amount",
            clean_name=clean,
            display_unit=normalize_raw_unit(raw_unit) or "currency",
            is_currency=True,
            is_percentage=False,
            is_multiple=False,
            short_display_name=short_title,
        )

    # 6. Other percentage keywords (CAGR, growth rate)
    if any(k in lower for k in _PERCENTAGE_OTHER_KEYWORDS):
        return MetricSemantic(
            metric_type="percentage",
            unit_family="percentage",
            semantic_type="growth_rate" if "growth" in lower or "cagr" in lower else "margin",
            clean_name=clean,
            display_unit="%",
            is_currency=False,
            is_percentage=True,
            is_multiple=False,
            short_display_name=short_title,
        )

    # 7. Fallback based on unit / raw_unit hints
    if unit == "multiple" or (raw_unit and raw_unit.strip().lower() in {"x", "times"}):
        return MetricSemantic(
            metric_type="multiple",
            unit_family="multiple",
            semantic_type="multiple",
            clean_name=clean,
            display_unit="x",
            is_currency=False,
            is_percentage=False,
            is_multiple=True,
            short_display_name=short_title,
        )
    if unit == "percent" or (raw_unit and "%" in raw_unit):
        return MetricSemantic(
            metric_type="percentage",
            unit_family="percentage",
            semantic_type="margin",
            clean_name=clean,
            display_unit="%",
            is_currency=False,
            is_percentage=True,
            is_multiple=False,
            is_expense_ratio=is_exp,
            short_display_name=short_title,
        )
    if unit == "currency" or (raw_unit and any(c in raw_unit for c in ("$", "£", "€", "¥", "RMB", "HKD", "USD", "CNY"))):
        return MetricSemantic(
            metric_type="currency",
            unit_family="currency",
            semantic_type="monetary_amount",
            clean_name=clean,
            display_unit=normalize_raw_unit(raw_unit) or "currency",
            is_currency=True,
            is_percentage=False,
            is_multiple=False,
            short_display_name=short_title,
        )

    return MetricSemantic(
        metric_type="generic",
        unit_family="generic",
        semantic_type="generic",
        clean_name=clean,
        display_unit=normalize_raw_unit(raw_unit) or "",
        is_currency=False,
        is_percentage=False,
        is_multiple=False,
        short_display_name=short_title,
    )


def is_currency_metric(name: str) -> bool:
    return classify_metric(name).is_currency


def is_percentage_metric(name: str) -> bool:
    return classify_metric(name).is_percentage


def is_multiple_metric(name: str) -> bool:
    return classify_metric(name).is_multiple


def format_metric_change(start: float, end: float, scale: float, semantic: MetricSemantic) -> str:
    """Format analytical change summary adhering to financial conventions.

    - Expense ratios: 'Cost of sales ratio increased by 6.6 pp' (never 'Loss widened')
    - Multiples change by '+0.20x' (never 'pp')
    - Percentages/margins change by '+2.0 pp'
    - Negative-to-negative currency changes explain 'Loss narrowed by X' or 'Loss widened by X'
    - Standard currency amounts change by '+15.2%'
    """
    name_lower = semantic.clean_name.casefold()
    is_liability = any(k in name_lower for k in ("liabilit", "borrowing", "debt", "indebtedness", "deficit", "负债", "借款"))

    if semantic.is_expense_ratio:
        s = abs(start)
        e = abs(end)
        diff = e - s
        direction = "increased" if diff >= 0 else "decreased"
        title = semantic.short_display_name or semantic.clean_name
        return f"{title} ratio {direction} by {abs(diff):.1f} pp"

    if start < 0 <= end:
        return "Turned positive"
    if start > 0 >= end:
        return "Turned negative"

    if start < 0 and end < 0:
        diff_scaled = abs(start - end) / scale
        if is_liability:
            return f"Liability narrowed by {diff_scaled:,.1f}" if end > start else f"Liability widened by {diff_scaled:,.1f}"
        if end > start:
            return f"Loss narrowed by {diff_scaled:,.1f}" if diff_scaled >= 1 else "Loss narrowed"
        return f"Loss widened by {diff_scaled:,.1f}" if diff_scaled >= 1 else "Loss widened"

    if is_liability and start > 0 and end > 0:
        diff_scaled = abs(end - start) / scale
        if end > start:
            return f"Widened by {diff_scaled:,.1f}" if diff_scaled >= 1 else "Widened"
        return f"Narrowed by {diff_scaled:,.1f}" if diff_scaled >= 1 else "Narrowed"

    if semantic.is_multiple or semantic.unit_family == "multiple":
        diff = end - start
        return f"{diff:+.2f}x"

    if semantic.is_percentage or semantic.unit_family == "percentage":
        diff = end - start
        return f"{diff:+.1f} pp"

    if start != 0:
        growth = (end / start - 1) * 100.0
        return f"{growth:+.1f}%"

    return f"{(end - start) / scale:+,.1f}"


def format_metric_display_value(
    raw_val: str,
    num_val: float | None,
    semantic: MetricSemantic,
    *,
    raw_unit: str | None = None,
    currency: str | None = None,
    compact: bool = False,
) -> str:
    """Format exact card display value based on typed semantics."""
    if semantic.is_multiple:
        clean = str(raw_val).rstrip("xX").strip()
        return f"{clean}x"
    if semantic.is_percentage:
        clean = str(raw_val).rstrip("%").strip()
        if semantic.is_expense_ratio and clean.startswith("-"):
            clean = clean.lstrip("-").strip()
        return f"{clean}%"
    if semantic.is_volume or semantic.unit_family == "count":
        return f"{raw_val}  units".strip()
    if semantic.is_currency:
        norm_unit = normalize_raw_unit(raw_unit, default_currency=currency or "RMB")
        if compact and num_val is not None:
            return format_compact_currency(num_val, raw_unit=raw_unit, currency=currency)
        if norm_unit and any(s in norm_unit.lower() for s in ("'000", "000", "thousand", "million", "billion")):
            unit_label = norm_unit
        else:
            unit_label = norm_unit or currency or "currency"
        return f"{raw_val}  {unit_label}".strip()
    norm_unit = normalize_raw_unit(raw_unit)
    return f"{raw_val}  {norm_unit or ''}".strip()


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
