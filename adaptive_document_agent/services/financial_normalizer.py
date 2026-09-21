"""Normalized financial data layer.

Transforms raw document observations into typed, validated, and normalized financial facts:
- Stores metric name, value, currency, unit, period, source page, audited status, IFRS/non-IFRS status, and confidence.
- Eliminates floating-point representation artifacts.
- Infers missing units (e.g. turnover days -> days, ratios -> multiple/percent).
- Distinguishes IFRS from Non-IFRS / Adjusted measures.
- Classifies period duration bases (FY, 6M, 3M, point_in_time) and audited vs unaudited.
"""

from __future__ import annotations

import math
import re
from typing import Any

from adaptive_document_agent.models import CanonicalFact, Observation
from adaptive_document_agent.services.financial_formatter import (
    normalize_currency_symbol,
    normalize_raw_unit,
)

# Explicit keywords marking non-IFRS / adjusted measures
_ADJUSTED_KEYWORDS = (
    "adjusted",
    "adj.",
    "adj ",
    "non-ifrs",
    "non ifrs",
    "non-gaap",
    "non gaap",
    "pro forma",
    "pro-forma",
    "经调整",
    "非国际财务报告准则",
    "非gaap",
    "剔除",
)

_DAYS_METRIC_KEYWORDS = (
    "turnover days",
    "days sales outstanding",
    "dso",
    "days inventory outstanding",
    "dio",
    "days payable outstanding",
    "dpo",
    "周转天数",
    "应收账款周转天数",
    "存货周转天数",
    "应付账款周转天数",
)

_MULTIPLE_METRIC_KEYWORDS = (
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


def clean_float_artifacts(val: float | None) -> float | None:
    """Eliminate floating point representation artifacts (e.g. 53.60000000000001 -> 53.6)."""
    if val is None:
        return None
    if math.isnan(val) or math.isinf(val):
        return None
    # If it is effectively an integer
    if abs(val - round(val)) < 1e-9:
        return float(round(val))
    # Round to 6 decimal places to discard IEEE 754 precision noise
    rounded = round(val, 6)
    if abs(rounded - round(val, 4)) < 1e-7:
        return round(val, 4)
    if abs(rounded - round(val, 2)) < 1e-5:
        return round(val, 2)
    return rounded


def format_clean_number_string(val: float | None) -> str:
    """Format float into clean presentation string without floating-point artifacts."""
    if val is None:
        return ""
    cleaned = clean_float_artifacts(val)
    if cleaned is None:
        return ""
    if cleaned.is_integer():
        return f"{int(cleaned):,}"
    # Format up to 2 decimal places if clean, otherwise strip trailing zeros
    s = f"{cleaned:,.4f}".rstrip("0").rstrip(".")
    return s


def classify_ifrs_status(metric_name: str, canonical_name: str | None = None) -> str:
    """Classify if a metric is standard IFRS or an Adjusted / Non-IFRS measure."""
    combined = f"{canonical_name or ''} {metric_name}".casefold()
    if any(k in combined for k in _ADJUSTED_KEYWORDS):
        return "ADJUSTED"
    return "IFRS"


class FinancialNormalizer:
    """Normalizes raw observations into high-integrity, typed canonical financial facts."""

    @classmethod
    def normalize_observation(
        cls,
        obs: Observation,
        *,
        default_currency: str = "RMB",
    ) -> Observation:
        """Deterministically normalize an Observation in-place and return it."""
        from adaptive_document_agent.document_model.metric_semantic_classifier import (
            classify_metric,
            is_days_metric,
            is_financial_statement_metric,
            is_margin_metric,
            is_multiple_metric,
            sanitize_metric_label,
        )
        from adaptive_document_agent.document_model.period_semantic_validator import (
            classify_period,
            extract_period_basis,
        )

        # 1. Floating-point cleanup
        obs.value = clean_float_artifacts(obs.value)

        # 2. Metric cleaning and IFRS classification
        metric_orig = obs.metric_original or ""
        metric_canon = obs.metric_canonical or ""
        obs.ifrs_status = classify_ifrs_status(metric_orig, metric_canon)

        # If metric is Adjusted / Non-IFRS, protect its canonical name from collapsing to unadjusted
        if obs.ifrs_status == "ADJUSTED" and metric_canon:
            if not any(k in metric_canon.casefold() for k in _ADJUSTED_KEYWORDS):
                # Canonical name lost the 'Adjusted' qualifier: restore it
                adj_prefix = "Adjusted " if not metric_canon.casefold().startswith("adjusted") else ""
                obs.metric_canonical = f"{adj_prefix}{metric_canon}"

        # 3. Unit and Currency Inference (never leave as 'unknown' for obvious metrics)
        lower_metric = f"{metric_orig} {metric_canon}".strip().casefold()
        current_unit = (obs.unit or "").strip().casefold()

        is_explicit_ratio = any(k in lower_metric for k in ("margin", "%", "share of", "ratio", "proportion", "growth rate", "cagr", "rate", "利润率", "占比", "比例", "增长率"))
        # Intrinsic units take precedence over financial-statement keywords.  For
        # example, "inventory turnover days" contains "inventory", but is not a
        # monetary balance-sheet amount.
        if is_days_metric(lower_metric) or any(k in lower_metric for k in _DAYS_METRIC_KEYWORDS):
            obs.unit = "days"
            obs.unit_family = "days"
            obs.display_unit = "days"
            obs.semantic_type = "days"
            obs.currency = None
        elif is_multiple_metric(lower_metric) or any(k in lower_metric for k in _MULTIPLE_METRIC_KEYWORDS):
            obs.unit = "multiple"
            obs.unit_family = "multiple"
            obs.display_unit = "x"
            obs.semantic_type = "multiple"
            obs.currency = None
        elif is_margin_metric(lower_metric):
            obs.unit = "percent"
            obs.unit_family = "percentage"
            obs.display_unit = "%"
            obs.semantic_type = "margin"
            obs.currency = None
            if obs.value is not None and abs(obs.value) > 1000.0 and hasattr(obs, "unit_scale") and (obs.unit_scale or 1.0) > 1.0:
                obs.value = clean_float_artifacts(obs.value / obs.unit_scale)
                obs.unit_scale = 1.0
        elif is_financial_statement_metric(lower_metric) and not is_explicit_ratio:
            obs.unit = "currency"
            obs.unit_family = "currency"
            obs.currency = obs.currency or default_currency
            obs.display_unit = obs.currency
            obs.semantic_type = "monetary_amount"
        elif current_unit in {"", "unknown", "none", "null"} or obs.unit is None:
            if any(k in lower_metric for k in ("margin", "%", "share of", "ratio", "proportion", "growth rate", "cagr", "rate")):
                obs.unit = "percent"
                obs.unit_family = "percentage"
                obs.display_unit = "%"
                obs.semantic_type = "margin" if "margin" in lower_metric or "利润率" in lower_metric else "ratio_share"
                obs.currency = None
            elif is_financial_statement_metric(lower_metric):
                obs.unit = "currency"
                obs.unit_family = "currency"
                obs.currency = obs.currency or default_currency
                obs.display_unit = obs.currency
                obs.semantic_type = "monetary_amount"
            else:
                # Fallback to general classifier
                sem = classify_metric(metric_orig, value=obs.value, raw_unit=obs.raw_unit, unit=obs.unit)
                if sem.unit_family != "generic":
                    obs.unit = sem.metric_type
                    obs.unit_family = sem.unit_family
                    obs.display_unit = sem.display_unit
                    obs.semantic_type = sem.semantic_type
                elif is_days_metric(metric_orig):
                    obs.unit = "days"
                    obs.unit_family = "days"
                    obs.display_unit = "days"
                    obs.semantic_type = "days"

        # Normalize currency symbol
        if obs.unit_family == "percentage" or obs.unit == "percent":
            obs.currency = None
        elif obs.currency:
            obs.currency = normalize_currency_symbol(obs.currency)

        # Normalize raw unit string if present
        if obs.raw_unit:
            obs.raw_unit = normalize_raw_unit(obs.raw_unit, default_currency=obs.currency or default_currency)

        # 4. Period Basis and Typing
        is_bs = obs.unit_family == "currency" and any(
            k in lower_metric for k in (
                "liabilit", "cash", "balance", "receiv", "payab", "inventor", "asset",
                "equity", "borrowing", "working capital", "net current", "资产", "负债", "资本"
            )
        )
        period_sem = classify_period(obs.period, is_balance_sheet=is_bs)
        obs.period_type = period_sem.period_type
        obs.period_basis = extract_period_basis(obs.period)

        if period_sem.as_of_date:
            obs.as_of_date = period_sem.as_of_date

        if period_sem.is_unaudited and obs.audited_status == "unknown":
            obs.audited_status = "unaudited"

        # 5. Presentation label & display value
        if not obs.presentation_label:
            obs.presentation_label = sanitize_metric_label(obs.metric_canonical or obs.metric_original)

        if not obs.display_value and obs.value is not None:
            obs.display_value = format_clean_number_string(obs.value)

        # 6. Fact type
        if not obs.fact_type or obs.fact_type == "reported_fact":
            obs.fact_type = "reported_fact"

        return obs

    @classmethod
    def normalize_observations(
        cls,
        observations: list[Observation],
        *,
        default_currency: str = "RMB",
    ) -> list[Observation]:
        """Normalize a collection of observations in-place."""
        for obs in observations:
            cls.normalize_observation(obs, default_currency=default_currency)
        return observations

    @classmethod
    def to_canonical_facts(cls, observations: list[Observation]) -> list[CanonicalFact]:
        """Convert a list of normalized Observations to CanonicalFact records."""
        facts: list[CanonicalFact] = []
        for obs in observations:
            cls.normalize_observation(obs)
            facts.append(CanonicalFact.from_observation(obs))
        return facts
