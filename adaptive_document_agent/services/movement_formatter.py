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
    is_expense_metric,
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

    @staticmethod
    def _scale_from_unit(unit: str | None, fallback: float = 1.0) -> float:
        """Return the numeric multiplier implied by a reported display unit."""
        if fallback and fallback != 1.0:
            return fallback
        unit_text = (unit or "").casefold()
        if any(token in unit_text for token in ("billion", " bn", "bn")):
            return 1_000_000_000.0
        if any(token in unit_text for token in ("million", " mn", "mn")):
            return 1_000_000.0
        if any(token in unit_text for token in ("thousand", "'000", "000s")):
            return 1_000.0
        return fallback or 1.0

    @classmethod
    def _format_currency_value(
        cls,
        value: float,
        *,
        currency: str,
        scale: float,
        unit: str | None,
    ) -> str:
        effective_scale = cls._scale_from_unit(unit, scale)
        effective_value = value * effective_scale if effective_scale > 1.0 and abs(value) < 100_000 else value
        return format_compact_currency(effective_value, currency=currency, is_base_value=True)

    @classmethod
    def analyze_trajectory(
        cls,
        values: list[float],
        periods: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze multi-period series for non-monotonic patterns: peaks, troughs, rebounds, plateaus."""
        if not values or len(values) < 3:
            return {"shape": "simple", "pattern": "simple", "description": ""}

        v_start = values[0]
        v_end = values[-1]
        v_max = max(values)
        v_min = min(values)
        i_max = values.index(v_max)
        i_min = values.index(v_min)
        n = len(values)
        val_span = abs(v_max - v_min) or 1.0

        p_start = periods[0] if (periods and len(periods) > 0) else ""
        p_end = periods[-1] if (periods and len(periods) > n - 1) else ""
        p_max = periods[i_max] if (periods and len(periods) > i_max) else ""
        p_min = periods[i_min] if (periods and len(periods) > i_min) else ""

        steps = [values[i + 1] - values[i] for i in range(n - 1)]

        # 1. Intermediate Peak: rises to a peak then falls (e.g. 30 -> 140 -> 260 -> 4.5)
        if (
            0 < i_max < n - 1
            and any(step > 0 for step in steps[:i_max])
            and any(step < 0 for step in steps[i_max:])
            and (v_max - max(v_start, v_end)) / val_span >= 0.05
        ):
            drop_from_peak = v_max - v_end
            if v_end < v_start or drop_from_peak / val_span >= 0.6:
                desc = "rising through middle periods before falling sharply"
                pattern = "rose_then_fell_sharply"
            else:
                desc = "rising to a peak before moderating"
                pattern = "rose_then_moderated"
            peak_where = f" in {p_max}" if p_max else ""
            end_where = f" in {p_end}" if p_end else ""
            return {
                "shape": pattern,
                "pattern": pattern,
                "peak_val": v_max,
                "peak_period": p_max,
                "description": f"Peaked at {v_max:.1f}{peak_where} before {'falling sharply' if pattern == 'rose_then_fell_sharply' else 'moderating'} to {v_end:.1f}{end_where}",
            }

        # 2. Intermediate Trough: falls to a low then recovers / rebounds (e.g. 100 -> 40 -> 85)
        if (
            0 < i_min < n - 1
            and any(step < 0 for step in steps[:i_min])
            and any(step > 0 for step in steps[i_min:])
            and (min(v_start, v_end) - v_min) / val_span >= 0.05
        ):
            if v_end >= v_start:
                desc = "dipping to a trough before rebounding"
                pattern = "fell_then_rebounded"
            else:
                desc = "falling to a trough before partially recovering"
                pattern = "fell_then_partially_recovered"
            trough_where = f" in {p_min}" if p_min else ""
            end_where = f" in {p_end}" if p_end else ""
            return {
                "shape": pattern,
                "pattern": pattern,
                "trough_val": v_min,
                "trough_period": p_min,
                "description": f"Reached a trough of {v_min:.1f}{trough_where} before {'rebounding' if pattern == 'fell_then_rebounded' else 'partially recovering'} to {v_end:.1f}{end_where}",
            }

        # 3. Stable then increased / decreased (Plateau followed by shift)
        if len(steps) >= 2:
            initial_values = values[:-1]
            initial_change = (max(initial_values) - min(initial_values)) / (abs(v_start) + 1e-6)
            final_change = abs(steps[-1]) / (abs(values[-2]) + 1e-6)
            if initial_change < 0.03 and final_change >= 0.08:
                direction = "increasing" if steps[-1] > 0 else "declining"
                return {
                    "shape": f"stable_then_{direction}",
                    "pattern": f"stable_then_{direction}",
                    "description": f"holding broadly flat before {direction}",
                }

        # 4. Monotonic
        if all(s >= 0 for s in steps):
            return {"shape": "monotonic_increase", "pattern": "monotonic_increase", "description": "expanding steadily"}
        if all(s <= 0 for s in steps):
            return {"shape": "monotonic_decrease", "pattern": "monotonic_decrease", "description": "contracting steadily"}

        return {"shape": "fluctuating", "pattern": "fluctuating", "description": "fluctuating across reported periods"}

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
        values: list[float] | None = None,
    ) -> str:
        """Generate standardized institutional movement text for a metric between two values."""
        clean_name = shorten_metric_title(metric_name)
        lower_name = f"{canonical_name or ''} {clean_name}".casefold()
        family = classify_metric_semantic_family(clean_name, canonical_name=canonical_name)
        prefix = f"{clean_name} " if include_metric_name else ""
        parent_mag = max(abs(start_val), abs(end_val))

        # 0a. DAYS Family (Turnover days, DSO, DIO, DPO, 周转天数)
        # Unit-aware: Always use 'days', NEVER 'pp' or '%'
        is_days = (
            family == getattr(MetricSemanticFamily, "DAYS", None)
            or unit_family == "days"
            or (unit and "day" in str(unit).casefold())
            or any(k in lower_name for k in ("turnover days", "dso", "dio", "dpo", "days sales", "days inventory", "days payable", "周转天数"))
        )
        if is_days:
            diff = end_val - start_val
            if values and len(values) >= 3:
                traj = cls.analyze_trajectory(values)
                if traj.get("pattern") in ("rose_then_fell_sharply", "rose_then_moderated"):
                    return f"{prefix}rose through middle periods before falling to {end_val:.1f} days"
                elif traj.get("pattern") in ("fell_then_rebounded", "fell_then_partially_recovered"):
                    return f"{prefix}dipped through middle periods before recovering to {end_val:.1f} days"
            verb = "increased" if diff >= 0 else "decreased"
            return f"{prefix}{verb} by {abs(diff):.1f} days" if abs(diff) >= 0.05 else f"{prefix}held flat"

        # 0b. MULTIPLES (Current ratio, Quick ratio, Gearing)
        if unit_family == "multiple" or family == getattr(MetricSemanticFamily, "MULTIPLE", None) or (unit and "multiple" in str(unit).casefold()) or (
            re.search(r"\b(?:multiple|leverage|gearing|current\s+ratio|quick\s+ratio)\b", lower_name)
            and not is_deficit_or_net_liability_metric(clean_name, canonical_name)
            and not any(k in lower_name for k in ("%", "share", "cost of", "selling", "r&d", "expense"))
        ):
            diff = end_val - start_val
            return f"{prefix}{diff:+.2f}x"

        # Full Trajectory Semantics: if multi-period series has a non-monotonic peak or trough
        is_percentage_series = family == MetricSemanticFamily.RATIO or unit_family == "percentage" or "%" in (unit or "") or (unit or "").casefold() in {"percent", "percentage"}
        if values and len(values) >= 3 and not is_percentage_series:
            traj = cls.analyze_trajectory(values)
            pattern = traj.get("pattern")
            if pattern == "rose_then_fell_sharply":
                return f"{prefix}rose through middle periods before falling sharply"
            elif pattern == "rose_then_moderated":
                return f"{prefix}rose to a peak before moderating"
            elif pattern == "fell_then_rebounded":
                return f"{prefix}dipped to a low before rebounding"
            elif pattern == "fell_then_partially_recovered":
                return f"{prefix}declined before partially recovering"
            elif pattern and pattern.startswith("stable_then_"):
                direction = "increasing" if "increasing" in pattern else "declining"
                return f"{prefix}held broadly flat before {direction}"

        # 1. EXPENSE Family
        if family == MetricSemanticFamily.EXPENSE or is_expense_metric(clean_name, canonical_name):
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
            if values and len(values) >= 3 and end_val < start_val and values[-1] > min(values):
                direction_str = "contracted overall" if is_margin else "declined overall"
                return f"{prefix}{direction_str} by {abs(diff):.1f} pp, with a partial rebound in the final period"
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
        values: list[float] | None = None,
        periods: list[str] | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> str:
        """Generate concise headline change for chart annotations, KPI badges, and callouts."""
        if values and len(values) >= 3:
            trajectory_periods = periods or ([start_period, end_period] if start_period and end_period and len(values) == 2 else None)
            traj = cls.analyze_trajectory(values, trajectory_periods)
            pattern = traj.get("pattern")
            if pattern == "rose_then_fell_sharply":
                return "Rose then fell sharply"
            elif pattern == "rose_then_moderated":
                return "Peaked then moderated"
            elif pattern == "fell_then_rebounded":
                return "Dipped then rebounded"
            elif pattern == "fell_then_partially_recovered":
                return "Fell then partially recovered"
            elif pattern and pattern.startswith("stable_then_"):
                return "Flat then increased" if "increasing" in pattern else "Flat then decreased"

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
            values=values,
        )

    @classmethod
    def format_movement_narrative(
        cls,
        first_obs: Any,
        last_obs: Any = None,
        *,
        start_val: float | None = None,
        end_val: float | None = None,
        unit: str | None = None,
        unit_family: str = "generic",
        start_period: str | None = None,
        end_period: str | None = None,
        currency: str = "RMB",
        scale: float = 1.0,
        values: list[float] | None = None,
        periods: list[str] | None = None,
        observations: list[Any] | None = None,
    ) -> str:
        """Generate complete analytical narrative sentence with canonical period labels for Key Findings."""
        if isinstance(first_obs, str):
            metric_name = first_obs
            canonical_name = None
            s_val = float(start_val if start_val is not None else (last_obs if isinstance(last_obs, (int, float)) else 0))
            e_val = float(end_val if end_val is not None else 0)
            period_first = start_period or "FY2021"
            period_last = end_period or "FY2022"
        else:
            metric_name = getattr(first_obs, "presentation_label", None) or getattr(first_obs, "metric_original", "")
            canonical_name = getattr(first_obs, "metric_canonical", None)
            s_val = float(getattr(first_obs, "value", 0) or 0)
            e_val = float(getattr(last_obs, "value", 0) or 0)
            period_first = format_observation_period(first_obs) or getattr(first_obs, "period", "")
            period_last = format_observation_period(last_obs) or getattr(last_obs, "period", "")

        clean_name = shorten_metric_title(metric_name)
        if values is None and observations:
            values = [float(getattr(o, "value", 0) or 0) for o in observations]
        if periods is None and observations:
            periods = [format_observation_period(o) or getattr(o, "period", "") for o in observations]

        family = classify_metric_semantic_family(clean_name, canonical_name=canonical_name)
        effective_scale = cls._scale_from_unit(unit, scale)
        is_percentage = family == MetricSemanticFamily.RATIO or unit_family == "percentage" or (unit or "").casefold() in {"percent", "percentage", "%"}
        is_days = (
            family == getattr(MetricSemanticFamily, "DAYS", None)
            or unit_family == "days"
            or (unit and "day" in str(unit).casefold())
            or any(k in clean_name.casefold() for k in ("turnover days", "dso", "dio", "dpo", "days sales", "days inventory", "days payable", "周转天数"))
        )

        def _series_value(value: float) -> str:
            if is_days:
                return f"{value:.1f} days"
            if unit_family == "multiple" or family == MetricSemanticFamily.MULTIPLE:
                return f"{value:.2f}x"
            if is_percentage:
                return f"{value:.1f}%"
            return cls._format_currency_value(value, currency=currency, scale=effective_scale, unit=unit)

        if values and len(values) >= 3:
            traj = cls.analyze_trajectory(values, periods)
            pattern = traj.get("pattern")
            p_first = periods[0] if periods else period_first
            p_last = periods[-1] if periods else period_last

            start_str = _series_value(values[0])
            end_str = _series_value(values[-1])

            if pattern == "rose_then_fell_sharply":
                peak_idx = values.index(max(values))
                peak_period = periods[peak_idx] if periods else ""
                peak_val = max(values)
                peak_str = _series_value(peak_val)
                period_clause = f"in {peak_period}" if peak_period else "the middle periods"
                return f"{clean_name} peaked at {peak_str} {period_clause} after rising through the middle periods, before falling sharply to {end_str} in {p_last} (from {start_str} in {p_first})."
            elif pattern == "rose_then_moderated":
                peak_idx = values.index(max(values))
                peak_period = periods[peak_idx] if periods else ""
                peak_val = max(values)
                peak_str = _series_value(peak_val)
                period_clause = f"in {peak_period}" if peak_period else "the middle periods"
                return f"{clean_name} rose to a peak of {peak_str} {period_clause} before moderating to {end_str} in {p_last} (from {start_str} in {p_first})."
            elif pattern in ("fell_then_rebounded", "fell_then_partially_recovered"):
                trough_idx = values.index(min(values))
                trough_period = periods[trough_idx] if periods else ""
                trough_val = min(values)
                trough_str = _series_value(trough_val)
                action = "rebounding" if pattern == "fell_then_rebounded" else "partially recovering"
                period_clause = f"in {trough_period}" if trough_period else "the middle periods"
                return f"{clean_name} declined to a low of {trough_str} {period_clause} before {action} to {end_str} in {p_last} (from {start_str} in {p_first})."
            elif pattern and pattern.startswith("stable_then_"):
                direction = "increasing" if "increasing" in pattern else "declining"
                return f"{clean_name} held broadly flat before {direction} to {end_str} in {p_last} (from {start_str} in {p_first})."

        movement_phrase = cls.format_movement(
            metric_name,
            s_val,
            e_val,
            canonical_name=canonical_name,
            currency=currency,
            scale=effective_scale,
            unit=unit,
            unit_family=unit_family,
            include_metric_name=True,
            values=values,
        )

        if is_days:
            return f"{movement_phrase} (from {s_val:.1f} days in {period_first} to {e_val:.1f} days in {period_last})."
        elif unit_family == "multiple" or family == getattr(MetricSemanticFamily, "MULTIPLE", None):
            diff = e_val - s_val
            verb = "increased" if diff >= 0 else "decreased"
            return f"{clean_name} {verb} by {abs(diff):.2f}x (from {s_val:.2f}x in {period_first} to {e_val:.2f}x in {period_last})."
        elif is_percentage:
            diff = e_val - s_val
            verb = "increased" if diff >= 0 else "decreased"
            return f"{clean_name} {verb} by {abs(diff):.1f} pp (from {s_val:.1f}% in {period_first} to {e_val:.1f}% in {period_last})."

        start_str = cls._format_currency_value(s_val, currency=currency, scale=effective_scale, unit=unit)
        end_str = cls._format_currency_value(e_val, currency=currency, scale=effective_scale, unit=unit)

        # For currency amounts, include percent change when informative
        pct_clause = ""
        if s_val > 0 and e_val > 0:
            pct = (e_val - s_val) / s_val * 100.0
            pct_clause = f" ({pct:+.1f}%)"

        return f"{movement_phrase}{pct_clause} (from {start_str} in {period_first} to {end_str} in {period_last})."


# Module-level convenience functions
analyze_trajectory = FinancialMovementFormatter.analyze_trajectory
format_movement = FinancialMovementFormatter.format_movement
format_movement_headline = FinancialMovementFormatter.format_movement_headline
format_movement_narrative = FinancialMovementFormatter.format_movement_narrative
