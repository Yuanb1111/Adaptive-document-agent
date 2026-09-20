"""Shared deterministic financial movement formatter for presentation and narrative generation.

Ensures institutional financial phrasing across all presentation layers:
- Key Findings
- KPI cards
- Chart annotations / callouts
- Analysis slide movement text
- Executive Summary
- Appendix narrative
"""

from __future__ import annotations

import re
from typing import Any

from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
from adaptive_document_agent.services.financial_formatter import format_compact_currency, shorten_metric_title
from adaptive_document_agent.validation.claim_validator import (
    MetricSemanticFamily,
    classify_metric_semantic_family,
    is_deficit_or_net_liability_metric,
)


class FinancialMovementFormatter:
    """Deterministic single shared formatting layer for financial movements."""

    @classmethod
    def _format_diff_amount(
        cls,
        diff_abs: float,
        currency: str = "RMB",
        scale: float = 1.0,
        parent_magnitude: float = 0.0,
    ) -> str:
        """Format an absolute difference amount compactly (e.g. 'RMB155m', 'RMB2.15bn', 'RMB0.74bn', '50.0')."""
        if not currency:
            diff_scaled = diff_abs / scale if scale and scale > 0 else diff_abs
            return f"{diff_scaled:,.1f}"

        curr = currency
        # If the metric is scaled in billions or base magnitude is >= 1 billion:
        if parent_magnitude >= 1_000_000_000 or (0.01 <= parent_magnitude < 100 and scale >= 1_000_000_000):
            if diff_abs >= 10_000_000:
                in_bn = diff_abs / 1_000_000_000.0
                return f"{curr}{in_bn:.2f}bn" if in_bn < 10 else f"{curr}{in_bn:.1f}bn"
            elif diff_abs < 100:
                return f"{curr}{diff_abs:.2f}bn" if diff_abs < 10 else f"{curr}{diff_abs:.1f}bn"
        elif 0.01 <= parent_magnitude < 10 and 0.01 <= diff_abs < 10:
            # Scaled billions passed directly (e.g. -1.57 -> -0.83, diff = 0.74; -4.47 -> -6.62, diff = 2.15)
            return f"{curr}{diff_abs:.2f}bn" if diff_abs < 10 else f"{curr}{diff_abs:.1f}bn"
        elif 10 <= parent_magnitude < 1000 and 1 <= diff_abs < 1000 and scale == 1.0 and not currency:
            # Small unscaled numbers without currency (e.g. -200 -> -150, diff = 50.0)
            return f"{diff_abs:,.1f}"

        effective_diff = diff_abs * scale if (scale and scale > 1.0 and parent_magnitude < 100_000) else diff_abs
        formatted = format_compact_currency(effective_diff, currency=currency, is_base_value=True)
        return re.sub(r"^(RMB|USD|HKD|CNY|EUR)\s+", r"\1", formatted)

    @classmethod
    def format_movement(
        cls,
        metric_name: str,
        start_val: float,
        end_val: float,
        *,
        canonical_name: str | None = None,
        currency: str = "RMB",
        scale: float = 1.0,
        unit: str | None = None,
        raw_unit: str | None = None,
        unit_family: str = "generic",
        include_metric_name: bool = True,
    ) -> str:
        """Generate standardized institutional movement text for a metric between two values."""
        clean_name = shorten_metric_title(metric_name)
        lower_name = f"{canonical_name or ''} {clean_name}".casefold()
        family = classify_metric_semantic_family(clean_name, canonical_name=canonical_name)
        prefix = f"{clean_name} " if include_metric_name else ""
        parent_mag = max(abs(start_val), abs(end_val))

        # 0. MULTIPLES (Current ratio, Quick ratio, Gearing)
        if unit_family == "multiple" or (unit and "multiple" in str(unit).casefold()) or (
            re.search(r"\b(?:multiple|leverage|gearing|current\s+ratio|quick\s+ratio)\b", lower_name)
            and not is_deficit_or_net_liability_metric(clean_name, canonical_name)
            and not any(k in lower_name for k in ("%", "share", "cost of", "selling", "r&d", "expense"))
        ):
            diff = end_val - start_val
            return f"{prefix}{diff:+.2f}x"

        # 1. EXPENSE Family
        if family == MetricSemanticFamily.EXPENSE:
            start_mag = abs(start_val)
            end_mag = abs(end_val)
            diff = abs(end_mag - start_mag)

            # Check if percentage ratio (e.g. Cost of sales / revenue)
            is_ratio = any(k in lower_name for k in ("ratio", "% of", "/ revenue", "share of revenue", "占比", "比例")) or "%" in (unit or "") or unit_family == "percentage"
            if is_ratio:
                direction = "increased" if end_mag > start_mag else "decreased"
                return f"{prefix}{direction} by {diff:.1f} pp" if diff >= 0.05 else (f"{prefix}remained flat" if include_metric_name else "Held flat")

            diff_str = cls._format_diff_amount(diff, currency=currency, scale=scale, parent_magnitude=parent_mag)
            # Slight change detection (< 3% relative change)
            if start_mag > 0 and (diff / start_mag) < 0.03 and diff > 0:
                if end_mag < start_mag:
                    return f"{prefix}decreased slightly"
                return f"{prefix}increased slightly"

            if end_mag < start_mag:
                return f"{prefix}decreased by {diff_str}"
            elif end_mag > start_mag:
                return f"{prefix}increased by {diff_str}"
            else:
                return f"{prefix}remained flat"

        # 2. CASH_FLOW Family
        if family == MetricSemanticFamily.CASH_FLOW:
            # Both negative: cash outflow
            if start_val < 0 and end_val < 0:
                s_mag = abs(start_val)
                e_mag = abs(end_val)
                diff = abs(s_mag - e_mag)
                diff_str = cls._format_diff_amount(diff, currency=currency, scale=scale, parent_magnitude=parent_mag)
                base_name = re.sub(r"(?i)\s+flow\b", "", clean_name).strip()
                outflow_name = f"{base_name} cash outflow" if "cash" not in base_name.lower() else f"{base_name} outflow"
                if e_mag < s_mag:
                    return f"{outflow_name} narrowed by {diff_str}" if include_metric_name else f"Outflow narrowed by {diff_str}"
                elif e_mag > s_mag:
                    return f"{outflow_name} increased by {diff_str}" if include_metric_name else f"Outflow increased by {diff_str}"
                else:
                    return f"{outflow_name} remained flat"

            # Reversals
            if start_val < 0 and end_val > 0:
                return f"{prefix}turned positive"
            if start_val > 0 and end_val < 0:
                return f"{prefix}turned negative"

            # Both positive
            diff = abs(end_val - start_val)
            diff_str = cls._format_diff_amount(diff, currency=currency, scale=scale, parent_magnitude=parent_mag)
            if end_val > start_val:
                return f"{prefix}increased by {diff_str}"
            elif end_val < start_val:
                return f"{prefix}decreased by {diff_str}"
            else:
                return f"{prefix}remained flat"

        # 3. Deficit / Net Liabilities (Net current liabilities, Net liabilities, Deficit, Shareholders' deficit)
        # Magnitude semantics: widened / narrowed. Standard liabilities (Current liabilities, Borrowings, etc.) use increased / decreased.
        if is_deficit_or_net_liability_metric(clean_name, canonical_name):
            s_mag = abs(start_val)
            e_mag = abs(end_val)
            diff = abs(e_mag - s_mag)
            diff_str = cls._format_diff_amount(diff, currency=currency, scale=scale, parent_magnitude=parent_mag)

            # More negative or larger deficit magnitude = widened / deteriorated
            if e_mag > s_mag:
                verb = "widened"
            elif e_mag < s_mag:
                verb = "narrowed"
            else:
                return f"{prefix}held flat" if include_metric_name else "Held flat"

            if include_metric_name:
                return f"{prefix}{verb} by {diff_str}"
            else:
                return f"{verb.capitalize()} by {diff_str}"

        # 4. PROFIT_LOSS Family
        if family == MetricSemanticFamily.PROFIT_LOSS:
            is_named_loss = "loss" in lower_name or "亏损" in lower_name
            is_gross_profit = "gross profit" in lower_name or "毛利" in lower_name

            # Zero-crossing
            if start_val < 0 and end_val > 0:
                if is_gross_profit:
                    return f"{prefix}turned into gross profit"
                return f"{prefix}turned profitable" if is_named_loss or "profit" in lower_name else f"{prefix}turned positive"
            if start_val > 0 and end_val < 0:
                if is_gross_profit:
                    return f"{prefix}turned into gross loss"
                return f"{prefix}swung into loss" if is_named_loss or "profit" in lower_name else f"{prefix}turned negative"

            # Both negative (Loss narrowed / widened)
            if start_val < 0 and end_val < 0:
                s_mag = abs(start_val)
                e_mag = abs(end_val)
                diff = abs(s_mag - e_mag)
                diff_str = cls._format_diff_amount(diff, currency=currency, scale=scale, parent_magnitude=parent_mag)
                if is_gross_profit:
                    loss_title = "Gross loss"
                elif is_named_loss:
                    loss_title = clean_name
                elif "net" in lower_name:
                    loss_title = "Net loss"
                elif "operating" in lower_name:
                    loss_title = "Operating loss"
                else:
                    loss_title = "Loss"
                verb = "narrowed" if e_mag < s_mag else "widened"
                if include_metric_name:
                    return f"{loss_title} {verb} by {diff_str}"
                else:
                    return f"Loss {verb} by {diff_str}"

            # Positive profit values
            diff = abs(end_val - start_val)
            diff_str = cls._format_diff_amount(diff, currency=currency, scale=scale, parent_magnitude=parent_mag)
            if end_val > start_val:
                return f"{prefix}increased by {diff_str}"
            elif end_val < start_val:
                return f"{prefix}decreased by {diff_str}"
            else:
                return f"{prefix}remained flat"

        # 5. RATIO / MARGIN Family
        if family == MetricSemanticFamily.RATIO or unit_family == "percentage" or "%" in (unit or ""):
            diff = end_val - start_val
            is_margin = any(k in lower_name for k in ("margin", "毛利", "净利", "利润率"))
            if is_margin:
                verb = "expanded" if diff >= 0 else "contracted"
            else:
                verb = "increased" if diff >= 0 else "decreased"
            return f"{prefix}{verb} by {abs(diff):.1f} pp" if abs(diff) >= 0.05 else f"{prefix}held flat"

        # 6. MULTIPLES
        if unit_family == "multiple" or "multiple" in lower_name or "ratio" in lower_name:
            diff = end_val - start_val
            return f"{prefix}{diff:+.2f}x"

        # 7. GENERIC (Revenue, Volume, etc.)
        diff = abs(end_val - start_val)
        diff_str = cls._format_diff_amount(diff, currency=currency, scale=scale, parent_magnitude=parent_mag)
        if end_val > start_val:
            return f"{prefix}increased by {diff_str}"
        elif end_val < start_val:
            return f"{prefix}decreased by {diff_str}"
        else:
            return f"{prefix}remained flat"

    @classmethod
    def format_movement_headline(
        cls,
        metric_name: str,
        start_val: float,
        end_val: float,
        *,
        canonical_name: str | None = None,
        currency: str = "RMB",
        scale: float = 1.0,
        unit: str | None = None,
        unit_family: str = "generic",
    ) -> str:
        """Generate concise headline change for chart annotations, KPI badges, and callouts."""
        return cls.format_movement(
            metric_name,
            start_val,
            end_val,
            canonical_name=canonical_name,
            currency=currency,
            scale=scale,
            unit=unit,
            unit_family=unit_family,
            include_metric_name=False,
        )

    @classmethod
    def format_movement_narrative(
        cls,
        first_obs: Any,
        last_obs: Any,
        *,
        currency: str = "RMB",
        scale: float = 1.0,
    ) -> str:
        """Generate complete analytical narrative sentence with canonical period labels for Key Findings."""
        metric_name = getattr(first_obs, "presentation_label", None) or getattr(first_obs, "metric_original", "")
        canonical_name = getattr(first_obs, "metric_canonical", None)
        start_val = float(getattr(first_obs, "value", 0) or 0)
        end_val = float(getattr(last_obs, "value", 0) or 0)

        # Canonical period formatting
        period_first = format_observation_period(first_obs) or getattr(first_obs, "period", "")
        period_last = format_observation_period(last_obs) or getattr(last_obs, "period", "")

        movement_phrase = cls.format_movement(
            metric_name,
            start_val,
            end_val,
            canonical_name=canonical_name,
            currency=currency,
            scale=scale,
            include_metric_name=True,
        )

        start_str = format_compact_currency(abs(start_val), currency=currency, is_base_value=True)
        end_str = format_compact_currency(abs(end_val), currency=currency, is_base_value=True)

        return f"{movement_phrase} (from {start_str} in {period_first} to {end_str} in {period_last})."
