"""Claim and directionality validator and repairer for presentation slides.

Validates that directional claims (increased, decreased, widened, narrowed, improved, deteriorated)
and quantitative assertions in presentation slides match underlying facts.

Rules:
1. Direction is determined by deterministic numeric logic, never LLM judgment.
2. Explicit trend states:
   - INCREASED, DECREASED, FLAT
   - LOSS_NARROWED (e.g. -562m -> -243m)
   - LOSS_WIDENED (e.g. -95m -> -569m)
   - LOSS_TO_PROFIT (e.g. -39m -> +12m)
   - PROFIT_TO_LOSS (e.g. +12m -> -39m)
   - AMBIGUOUS
3. For LOSS_TO_PROFIT:
   - Use wording: "turned profitable", "reversed from loss to profit"
   - Only if metric semantics confirm positive means profit.
   - If metric itself is "loss" and sign semantics are ambiguous, block export instead of guessing.
4. Structured repair:
   - ClaimValidator returns structured DirectionalClaimIssue objects with exact slide_id,
     metric_name, start_value, end_value, expected_direction, offending_direction,
     and target_component.
   - Repairs are performed directly on structured issues rather than re-inferring text relevance.
5. Verification loop:
   Presentation Plan -> Claim Validator -> Structured Repair -> Claim Validator (Revalidate)
   Export only if the second validation passes cleanly.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Any

from adaptive_document_agent.document_model import period_sort_key
from adaptive_document_agent.models import Observation, PresentationPlan, PresentationSlide, ValidationIssue


class MetricSemanticFamily(str, Enum):
    PROFIT_LOSS = "PROFIT_LOSS"
    CASH_FLOW = "CASH_FLOW"
    EXPENSE = "EXPENSE"
    BALANCE_SHEET = "BALANCE_SHEET"
    RATIO = "RATIO"
    GENERIC = "GENERIC"


class BalanceSheetSubtype(str, Enum):
    STANDARD = "STANDARD"
    DEFICIT_OR_NET_LIABILITY = "DEFICIT_OR_NET_LIABILITY"


class TrendState(str, Enum):
    INCREASED = "INCREASED"
    DECREASED = "DECREASED"
    FLAT = "FLAT"
    LOSS_NARROWED = "LOSS_NARROWED"
    LOSS_WIDENED = "LOSS_WIDENED"
    LOSS_TO_PROFIT = "LOSS_TO_PROFIT"
    PROFIT_TO_LOSS = "PROFIT_TO_LOSS"
    GAIN_TO_LOSS = "GAIN_TO_LOSS"
    LOSS_TO_GAIN = "LOSS_TO_GAIN"
    TURNED_POSITIVE = "TURNED_POSITIVE"
    TURNED_NEGATIVE = "TURNED_NEGATIVE"
    DEFICIT_WIDENED = "DEFICIT_WIDENED"
    DEFICIT_NARROWED = "DEFICIT_NARROWED"
    AMBIGUOUS = "AMBIGUOUS"


class DirectionalClaimIssue(ValidationIssue):
    """Structured validation issue capturing exact directional contradiction details."""

    slide_id: str = ""
    metric_name: str = ""
    semantic_family: str = ""  # MetricSemanticFamily string
    balance_sheet_subtype: str = ""  # BalanceSheetSubtype string
    start_value: float = 0.0
    end_value: float = 0.0
    expected_direction: str = ""  # TrendState string
    offending_direction: str = ""  # Contradictory word/phrase in text
    target_component: str = ""  # "title", "message", "bullet"
    bullet_index: int | None = None


def are_observations_compatible(obs1: Observation, obs2: Observation) -> tuple[bool, str]:
    """Verify that two observations can be safely compared for directional changes."""
    # 1. Canonical metric
    m1 = (obs1.metric_canonical or obs1.metric_original).strip().casefold()
    m2 = (obs2.metric_canonical or obs2.metric_original).strip().casefold()
    if obs1.metric_canonical and obs2.metric_canonical:
        if obs1.metric_canonical.strip().casefold() != obs2.metric_canonical.strip().casefold():
            return False, f"Canonical metric mismatch: '{obs1.metric_canonical}' vs '{obs2.metric_canonical}'"
    elif m1 != m2:
        return False, f"Metric name mismatch: '{m1}' vs '{m2}'"

    # 2. Units & Unit family
    u1_fam = (obs1.unit_family or "").strip().casefold()
    u2_fam = (obs2.unit_family or "").strip().casefold()
    if u1_fam and u2_fam and u1_fam != "generic" and u2_fam != "generic" and u1_fam != u2_fam:
        return False, f"Incompatible unit families: '{u1_fam}' vs '{u2_fam}'"

    unit1 = (obs1.unit or obs1.raw_unit or "").strip().casefold()
    unit2 = (obs2.unit or obs2.raw_unit or "").strip().casefold()
    is_pct1 = "%" in unit1 or u1_fam == "percentage"
    is_pct2 = "%" in unit2 or u2_fam == "percentage"
    if is_pct1 != is_pct2:
        return False, f"Incompatible unit types: '{unit1}' vs '{unit2}' (percentage vs non-percentage)"

    # 3. Currency
    curr1 = (obs1.currency or "").strip().upper()
    curr2 = (obs2.currency or "").strip().upper()
    if curr1 and curr2 and curr1 != curr2:
        return False, f"Currency mismatch: '{curr1}' vs '{curr2}'"
    if (curr1 and not curr2 and u2_fam == "currency") or (curr2 and not curr1 and u1_fam == "currency"):
        return False, f"Currency specification mismatch: '{curr1 or 'unspecified'}' vs '{curr2 or 'unspecified'}'"

    # 4. Period types
    p1 = (obs1.period_type or "generic").strip().casefold()
    p2 = (obs2.period_type or "generic").strip().casefold()
    if p1 != "generic" and p2 != "generic":
        if (p1 == "balance_sheet_date" and p2 in ("fiscal_year", "interim_flow")) or (
            p2 == "balance_sheet_date" and p1 in ("fiscal_year", "interim_flow")
        ):
            return False, f"Incompatible period types: balance sheet point-in-time '{p1}' vs flow period '{p2}'"
        if (p1 == "fiscal_year" and p2 == "interim_flow") or (p2 == "fiscal_year" and p1 == "interim_flow"):
            return False, f"Incompatible period types: full fiscal year '{p1}' vs interim flow '{p2}'"

    # 5. Reporting basis
    b1 = (obs1.dimensions.get("reporting_basis") or obs1.dimensions.get("basis") or "").strip().casefold()
    b2 = (obs2.dimensions.get("reporting_basis") or obs2.dimensions.get("basis") or "").strip().casefold()
    if b1 and b2 and b1 != b2:
        return False, f"Incompatible reporting basis: '{b1}' vs '{b2}'"

    r1 = (obs1.dimensions.get("restatement") or obs1.dimensions.get("restated") or "").strip().casefold()
    r2 = (obs2.dimensions.get("restatement") or obs2.dimensions.get("restated") or "").strip().casefold()
    if r1 and r2 and r1 != r2:
        return False, f"Incompatible restatement basis: '{r1}' vs '{r2}'"

    return True, ""


def classify_metric_semantic_family(
    metric_name: str,
    canonical_name: str | None = None,
) -> MetricSemanticFamily:
    """Classify the semantic family of a financial metric.

    Families:
    - CASH_FLOW: cash flows, operating/investing/financing cash, cash generated
    - EXPENSE: costs, expenses, R&D, SG&A, depreciation, employee benefits
    - RATIO: margins, ratios, percentages, growth rates
    - PROFIT_LOSS: net profit, operating profit, net income, ebit, losses
    - BALANCE_SHEET: assets, liabilities, equity, receivables, payables, borrowings
    - GENERIC: revenue, volume, headcount, etc.
    """
    name_str = f"{canonical_name or ''} {metric_name}".strip().casefold()
    name_normalized = re.sub(r"[_\-]+", " ", name_str)

    # 1. CASH_FLOW (must precede PROFIT_LOSS so 'operating cash flow' != 'operating profit')
    cash_flow_indicators = (
        "cash flow",
        "operating cash",
        "investing cash",
        "financing cash",
        "free cash flow",
        "cash generated",
        "cash from operations",
        "cash used",
        "cash outflow",
        "cash inflow",
        "现金流",
        "经营活动现金",
        "经营现金",
        "投资活动现金",
        "筹资活动现金",
    )
    if any(p in name_normalized for p in cash_flow_indicators):
        return MetricSemanticFamily.CASH_FLOW

    # 2. RATIO (margins, percentages, multipliers)
    ratio_indicators = (
        "margin",
        "ratio",
        "% of",
        "percentage",
        "multiple",
        "turnover days",
        "cagr",
        "bps",
        "毛利率",
        "净利率",
        "营业利润率",
        "负债率",
    )
    if any(p in name_normalized for p in ratio_indicators):
        return MetricSemanticFamily.RATIO

    # 3. EXPENSE (costs, expenses, R&D, D&A, finance costs)
    expense_indicators = (
        "expense",
        "cost of",
        "operating cost",
        "r&d",
        "research and development",
        "selling",
        "administrative",
        "depreciation",
        "amortization",
        "impairment",
        "credit loss",
        "staff cost",
        "employee benefit",
        "finance cost",
        "tax expense",
        "taxation",
        "费用",
        "营业成本",
        "研发费用",
        "管理费用",
        "销售费用",
        "财务费用",
    )
    if any(p in name_normalized for p in expense_indicators) or re.search(r"\bcosts?\b", name_normalized) or re.search(r"\bexpenses?\b", name_normalized):
        return MetricSemanticFamily.EXPENSE

    # 4. PROFIT_LOSS (net profit, loss, ebit, ebitda, net income)
    pl_indicators = (
        "profit",
        "net income",
        "operating income",
        "ebit",
        "ebitda",
        "net result",
        "净利润",
        "净亏损",
        "营业利润",
        "营业亏损",
        "利润总额",
        "亏损",
    )
    if any(p in name_normalized for p in pl_indicators) or re.search(r"\bloss(?:es)?\b", name_normalized):
        if "impairment" in name_normalized or "credit loss" in name_normalized:
            return MetricSemanticFamily.EXPENSE
        return MetricSemanticFamily.PROFIT_LOSS

    # 5. BALANCE_SHEET (assets, liabilities, equity, cash balance)
    bs_indicators = (
        "assets",
        "asset",
        "liabilities",
        "liability",
        "equity",
        "receivable",
        "receivables",
        "payable",
        "payables",
        "inventory",
        "inventories",
        "borrowing",
        "borrowings",
        "debt",
        "cash and cash equivalents",
        "deficit",
        "working capital",
        "资产",
        "负债",
        "所有者权益",
        "股东权益",
        "应收",
        "应付",
        "存货",
        "借款",
    )
    if any(p in name_normalized for p in bs_indicators):
        return MetricSemanticFamily.BALANCE_SHEET

    return MetricSemanticFamily.GENERIC


def is_deficit_or_net_liability_metric(
    metric_name: str,
    canonical_name: str | None = None,
) -> bool:
    """Determine if a balance sheet metric represents a deficit or net liability position."""
    name_str = f"{canonical_name or ''} {metric_name}".strip().casefold()
    name_norm = re.sub(r"[_\-]+", " ", name_str)

    deficit_indicators = (
        "net current liabilities",
        "net current liability",
        "net liabilities",
        "net liability",
        "shareholders deficit",
        "shareholder deficit",
        "shareholders' deficit",
        "total deficit",
        "negative working capital",
        "working capital deficit",
        "net asset deficit",
        "net assets deficit",
    )
    if any(p in name_norm for p in deficit_indicators):
        return True
    if re.search(r"\bdeficits?\b", name_norm):
        return True
    return False


def classify_balance_sheet_subtype(
    metric_name: str,
    canonical_name: str | None = None,
) -> BalanceSheetSubtype:
    """Classify the balance-sheet sign semantic subtype."""
    if is_deficit_or_net_liability_metric(metric_name, canonical_name):
        return BalanceSheetSubtype.DEFICIT_OR_NET_LIABILITY
    return BalanceSheetSubtype.STANDARD


def is_signed_gain_loss_metric(
    metric_name: str,
    canonical_name: str | None = None,
) -> bool:
    """Determine if a metric represents a signed gain/(loss) accounting line item.

    Examples:
    - Net foreign exchange gain/(loss)
    - fair-value gain/(loss)
    - FX gain/(loss)
    """
    cn = canonical_name or ""
    name_str = f"{cn} {metric_name}".strip().casefold()
    name_norm = re.sub(r"[_\-]+", " ", name_str)
    if re.search(r"gain\s*[\(\/\\]\s*loss", name_norm) or re.search(r"loss\s*[\(\/\\]\s*gain", name_norm):
        return True
    if any(
        p in name_norm
        for p in (
            "gain or loss",
            "loss or gain",
            "fx gain",
            "fx loss",
            "foreign exchange gain",
            "foreign exchange loss",
            "fair value gain",
            "fair value loss",
            "exchange gain",
            "exchange loss",
        )
    ):
        return True
    return False


def determine_trend_state(
    metric_name: str,
    val_start: float,
    val_end: float,
    canonical_name: str | None = None,
) -> TrendState:
    """Deterministically determine the trend state by classifying semantic family first."""
    family = classify_metric_semantic_family(metric_name, canonical_name)
    metric_normalized = re.sub(r"[_\-]+", " ", f"{canonical_name or ''} {metric_name}".strip().casefold())

    if val_start == val_end:
        return TrendState.FLAT

    # 0. Signed gain/(loss) accounting line items (never ambiguous on zero-crossing)
    if is_signed_gain_loss_metric(metric_name, canonical_name):
        if val_start > 0 and val_end < 0:
            return TrendState.GAIN_TO_LOSS
        if val_start < 0 and val_end > 0:
            return TrendState.LOSS_TO_GAIN
        if val_start < 0 and val_end < 0:
            abs_start = abs(val_start)
            abs_end = abs(val_end)
            if abs_end < abs_start:
                return TrendState.LOSS_NARROWED
            elif abs_end > abs_start:
                return TrendState.LOSS_WIDENED
            else:
                return TrendState.FLAT
        if val_start >= 0 and val_end >= 0:
            diff = val_end - val_start
            if diff > 0:
                return TrendState.INCREASED
            elif diff < 0:
                return TrendState.DECREASED
            else:
                return TrendState.FLAT

    # 1. EXPENSE Family
    if family == MetricSemanticFamily.EXPENSE:
        # Expenses: increased expense means magnitude grew; decreased means magnitude shrank
        if val_start <= 0 and val_end <= 0:
            abs_start = abs(val_start)
            abs_end = abs(val_end)
            if abs_end > abs_start:
                return TrendState.INCREASED
            elif abs_end < abs_start:
                return TrendState.DECREASED
            else:
                return TrendState.FLAT
        elif val_start >= 0 and val_end >= 0:
            if val_end > val_start:
                return TrendState.INCREASED
            elif val_end < val_start:
                return TrendState.DECREASED
            else:
                return TrendState.FLAT
        else:
            return TrendState.TURNED_POSITIVE if val_end > 0 else TrendState.TURNED_NEGATIVE

    # 2. CASH_FLOW Family
    if family == MetricSemanticFamily.CASH_FLOW:
        # Transition across zero
        if val_start < 0 and val_end > 0:
            return TrendState.TURNED_POSITIVE
        if val_start > 0 and val_end < 0:
            return TrendState.TURNED_NEGATIVE
        # Numeric difference: -100 -> -50 is diff = +50 (value increased / cash outflow narrowed)
        diff = val_end - val_start
        if diff > 0:
            return TrendState.INCREASED
        elif diff < 0:
            return TrendState.DECREASED
        else:
            return TrendState.FLAT

    # 3. PROFIT_LOSS Family
    if family == MetricSemanticFamily.PROFIT_LOSS:
        is_profit_confirmed = (
            canonical_name in (
                "net_income", "operating_profit", "gross_profit", "profit_for_the_year",
                "profit_before_tax", "ebitda", "operating_income", "net_profit"
            )
            or any(p in metric_normalized for p in ("profit", "income", "earnings", "ebit", "result"))
        )

        is_named_loss_only = (
            "loss" in metric_normalized
            and not any(p in metric_normalized for p in ("profit", "income", "earnings", "ebit", "result"))
        )

        # Transition from negative to positive
        if val_start < 0 and val_end > 0:
            if is_profit_confirmed:
                return TrendState.LOSS_TO_PROFIT
            elif is_named_loss_only:
                # Metric itself is "loss" and sign semantics are ambiguous: block export instead of guessing
                return TrendState.AMBIGUOUS
            else:
                return TrendState.LOSS_TO_PROFIT

        # Transition from positive to negative
        if val_start > 0 and val_end < 0:
            if is_profit_confirmed:
                return TrendState.PROFIT_TO_LOSS
            elif is_named_loss_only:
                return TrendState.AMBIGUOUS
            else:
                return TrendState.PROFIT_TO_LOSS

        # Both values negative
        if val_start < 0 and val_end < 0:
            abs_start = abs(val_start)
            abs_end = abs(val_end)
            if abs_end < abs_start:
                return TrendState.LOSS_NARROWED
            elif abs_end > abs_start:
                return TrendState.LOSS_WIDENED
            else:
                return TrendState.FLAT

        # Both values positive under a metric explicitly named "loss"
        if is_named_loss_only and val_start > 0 and val_end > 0:
            if val_end < val_start:
                return TrendState.LOSS_NARROWED
            elif val_end > val_start:
                return TrendState.LOSS_WIDENED
            else:
                return TrendState.FLAT

        # Standard profit metrics (e.g. 100 -> 150)
        diff = val_end - val_start
        if diff > 0:
            return TrendState.INCREASED
        elif diff < 0:
            return TrendState.DECREASED
        else:
            return TrendState.FLAT

    # 4. BALANCE_SHEET Family
    if family == MetricSemanticFamily.BALANCE_SHEET:
        if is_deficit_or_net_liability_metric(metric_name, canonical_name):
            # Magnitude semantics for deficit / net liability position metrics:
            # - more negative = widened / deteriorated (e.g. -4.47bn -> -6.62bn)
            # - closer to zero = narrowed / improved (e.g. -6.62bn -> -4.47bn)
            if val_start <= 0 and val_end <= 0:
                abs_start = abs(val_start)
                abs_end = abs(val_end)
                if abs_end > abs_start:
                    return TrendState.DEFICIT_WIDENED
                elif abs_end < abs_start:
                    return TrendState.DEFICIT_NARROWED
                else:
                    return TrendState.FLAT
            elif val_start >= 0 and val_end >= 0:
                if val_end > val_start:
                    return TrendState.DEFICIT_WIDENED
                elif val_end < val_start:
                    return TrendState.DEFICIT_NARROWED
                else:
                    return TrendState.FLAT
            else:
                return TrendState.TURNED_POSITIVE if val_end > 0 else TrendState.TURNED_NEGATIVE
        else:
            # Standard balance sheet metrics (assets, cash, normal liabilities, equity)
            if val_start < 0 and val_end > 0:
                return TrendState.TURNED_POSITIVE
            if val_start > 0 and val_end < 0:
                return TrendState.TURNED_NEGATIVE
            diff = val_end - val_start
            if diff > 0:
                return TrendState.INCREASED
            elif diff < 0:
                return TrendState.DECREASED
            else:
                return TrendState.FLAT

    # 5. RATIO, GENERIC Families
    if val_start < 0 and val_end > 0:
        return TrendState.TURNED_POSITIVE
    if val_start > 0 and val_end < 0:
        return TrendState.TURNED_NEGATIVE

    diff = val_end - val_start
    if diff > 0:
        return TrendState.INCREASED
    elif diff < 0:
        return TrendState.DECREASED
    else:
        return TrendState.FLAT


def replace_word_preserving_case(text: str, target: str, replacement: str) -> tuple[str, bool]:
    """Replace a word or phrase preserving uppercase or capitalized casing."""
    pattern = re.compile(r"\b" + re.escape(target) + r"\b", re.IGNORECASE)
    replaced = False

    def _repl(match: re.Match) -> str:
        nonlocal replaced
        replaced = True
        matched = match.group(0)
        if matched.isupper():
            return replacement.upper()
        if matched[0].isupper():
            return replacement.capitalize()
        return replacement.lower()

    new_text = pattern.sub(_repl, text)
    return new_text, replaced


# Mappings for standard metrics (non-loss)
# Forbidden loss words/phrases for non-profit/loss metrics
_FORBIDDEN_NON_PROFIT_LOSS_PHRASES: list[str] = [
    "turned profitable",
    "reversed from loss to profit",
    "swung into loss",
    "reversed from profit to loss",
    "reversal to loss",
    "loss narrowed",
    "loss narrowing",
    "loss widened",
    "loss widening",
]

# Mappings for standard metrics (non-loss)
_STANDARD_INCREASE_REPLACEMENTS: dict[str, str] = {
    "declined": "increased",
    "declining": "increasing",
    "declines": "increases",
    "decline": "increase",
    "decreased": "increased",
    "decreasing": "increasing",
    "decreases": "increases",
    "decrease": "increase",
    "fell": "rose",
    "falling": "rising",
    "falls": "rises",
    "fall": "rise",
    "dropped": "rose",
    "dropping": "rising",
    "drops": "rises",
    "drop": "rise",
    "contracted": "expanded",
    "contracting": "expanding",
    "contraction": "expansion",
    "slumped": "surged",
    "narrowed": "expanded",
}

_STANDARD_DECREASE_REPLACEMENTS: dict[str, str] = {
    "increased": "decreased",
    "increasing": "decreasing",
    "increases": "decreases",
    "increase": "decrease",
    "grew": "declined",
    "growth": "decline",
    "growing": "declining",
    "grow": "decline",
    "rose": "fell",
    "rising": "falling",
    "rises": "falls",
    "rise": "fall",
    "expanded": "contracted",
    "expanding": "contracting",
    "expansion": "contraction",
    "surged": "slumped",
    "widened": "contracted",
}

_CASH_FLOW_INCREASE_REPLACEMENTS: dict[str, str] = {
    k: v for k, v in _STANDARD_INCREASE_REPLACEMENTS.items() if k != "narrowed"
}
_CASH_FLOW_INCREASE_REPLACEMENTS.update({
    "cash outflow widened": "cash outflow narrowed",
    "outflow widened": "cash outflow narrowed",
    "loss narrowed": "cash outflow narrowed",
    "loss widened": "cash outflow narrowed",
    "widened": "cash outflow narrowed",
})

_EXPENSE_INCREASE_REPLACEMENTS: dict[str, str] = {
    **_STANDARD_INCREASE_REPLACEMENTS,
    "loss widened": "increased",
    "loss narrowed": "increased",
    "widened": "increased",
    "narrowed": "increased",
}

_EXPENSE_DECREASE_REPLACEMENTS: dict[str, str] = {
    **_STANDARD_DECREASE_REPLACEMENTS,
    "loss narrowed": "decreased",
    "loss widened": "decreased",
    "widened": "decreased",
    "narrowed": "decreased",
}

_TURNED_POSITIVE_REPLACEMENTS: dict[str, str] = {
    "turned profitable": "turned positive",
    "reversed from loss to profit": "turned positive",
    "swung into loss": "turned positive",
    "loss narrowed": "turned positive",
    "loss widened": "turned positive",
    "declined": "turned positive",
    "decreased": "turned positive",
    "fell": "turned positive",
    "dropped": "turned positive",
    "deteriorated": "turned positive",
    "widened": "turned positive",
    "narrowed": "turned positive",
}

_TURNED_NEGATIVE_REPLACEMENTS: dict[str, str] = {
    "swung into loss": "turned negative",
    "reversed from profit to loss": "turned negative",
    "reversal to loss": "turned negative",
    "turned profitable": "turned negative",
    "improved": "turned negative",
    "increased": "turned negative",
    "grew": "turned negative",
    "rose": "turned negative",
    "expanded": "turned negative",
}

# Mappings for loss metrics
_LOSS_NARROWED_REPLACEMENTS: dict[str, str] = {
    "widened": "narrowed",
    "widening": "narrowing",
    "widens": "narrows",
    "widen": "narrow",
    "deteriorated": "improved",
    "deteriorating": "improving",
    "deteriorates": "improves",
    "deterioration": "improvement",
    "increased": "narrowed",
    "increasing": "narrowing",
    "increases": "narrows",
    "grew": "narrowed",
    "expanded": "narrowed",
}

_LOSS_WIDENED_REPLACEMENTS: dict[str, str] = {
    "narrowed": "widened",
    "narrowing": "widening",
    "narrows": "widens",
    "narrow": "widen",
    "improved": "deteriorated",
    "improving": "deteriorating",
    "improves": "deteriorates",
    "improvement": "deterioration",
    "decreased": "widened",
    "decreasing": "widening",
    "decreases": "widens",
    "declined": "widened",
    "declining": "widening",
    "declines": "widens",
    "contracted": "widened",
    "fell": "widened",
    "dropped": "widened",
}

# Mappings for loss to profit
_LOSS_TO_PROFIT_REPLACEMENTS: dict[str, str] = {
    "loss widened": "turned profitable",
    "loss narrowed": "turned profitable",
    "widened": "turned profitable",
    "narrowed": "turned profitable",
    "deteriorated": "turned profitable",
    "declined": "turned profitable",
    "decreased": "reversed from loss to profit",
}

# Mappings for profit to loss
_PROFIT_TO_LOSS_REPLACEMENTS: dict[str, str] = {
    "improved": "swung into loss",
    "increased": "reversed from profit to loss",
    "grew": "swung into loss",
    "growth": "reversal to loss",
}

# Mappings for balance sheet deficit / net liability position metrics
_DEFICIT_WIDENED_REPLACEMENTS: dict[str, str] = {
    "decreased": "widened",
    "decreasing": "widening",
    "decreases": "widens",
    "decrease": "widen",
    "contracted": "widened",
    "contracting": "widening",
    "contraction": "widening",
    "narrowed": "widened",
    "narrowing": "widening",
    "narrows": "widens",
    "narrow": "widen",
    "fell": "widened",
    "dropped": "widened",
    "improved": "deteriorated",
    "improving": "deteriorating",
    "improves": "deteriorates",
    "improvement": "deterioration",
}

_DEFICIT_NARROWED_REPLACEMENTS: dict[str, str] = {
    "increased": "narrowed",
    "increasing": "narrowing",
    "increases": "narrows",
    "increase": "narrow",
    "expanded": "narrowed",
    "expanding": "narrowing",
    "expansion": "narrowing",
    "widened": "narrowed",
    "widening": "narrowing",
    "widens": "narrows",
    "widen": "narrow",
    "rose": "narrowed",
    "grew": "narrowed",
    "deteriorated": "improved",
    "deteriorating": "improving",
    "deteriorates": "improves",
    "deterioration": "improvement",
}

_GAIN_TO_LOSS_REPLACEMENTS: dict[str, str] = {
    "improved": "swung from gain to loss",
    "improving": "swinging from gain to loss",
    "increased": "swung from gain to loss",
    "increasing": "swinging from gain to loss",
    "increases": "swings from gain to loss",
    "increase": "swing from gain to loss",
    "grew": "swung from gain to loss",
    "growing": "swinging from gain to loss",
    "growth": "reversal to loss",
    "rose": "swung from gain to loss",
    "rising": "swinging from gain to loss",
    "turned profitable": "swung from gain to loss",
    "turned positive": "swung from gain to loss",
    "narrowed": "swung from gain to loss",
    "expanded": "swung from gain to loss",
}

_LOSS_TO_GAIN_REPLACEMENTS: dict[str, str] = {
    "deteriorated": "swung from loss to gain",
    "deteriorating": "swinging from loss to gain",
    "decreased": "swung from loss to gain",
    "decreasing": "swinging from loss to gain",
    "decreases": "swings from loss to gain",
    "decrease": "swing from loss to gain",
    "declined": "swung from loss to gain",
    "declining": "swinging from loss to gain",
    "declines": "swings from loss to gain",
    "decline": "swing from loss to gain",
    "fell": "swung from loss to gain",
    "falling": "swinging from loss to gain",
    "dropped": "swung from loss to gain",
    "dropping": "swinging from loss to gain",
    "swung into loss": "swung from loss to gain",
    "turned negative": "swung from loss to gain",
    "widened": "swung from loss to gain",
    "widening": "swinging from loss to gain",
}


def _detect_offending_in_text(
    text: str,
    trend_state: TrendState,
    family: MetricSemanticFamily = MetricSemanticFamily.GENERIC,
) -> str | None:
    """Find any contradictory directional words or phrases in text based on trend state and family."""
    text_lower = text.casefold()

    # Rule: For non-profit/loss metrics, never generate or allow loss terminology
    if family != MetricSemanticFamily.PROFIT_LOSS:
        for bad_phrase in _FORBIDDEN_NON_PROFIT_LOSS_PHRASES:
            if re.search(r"\b" + re.escape(bad_phrase) + r"\b", text_lower):
                return bad_phrase

    if trend_state == TrendState.LOSS_NARROWED:
        for bad_word in _LOSS_NARROWED_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.LOSS_WIDENED:
        for bad_word in _LOSS_WIDENED_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.LOSS_TO_PROFIT:
        for bad_phrase in _LOSS_TO_PROFIT_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_phrase) + r"\b", text_lower):
                return bad_phrase
    elif trend_state == TrendState.PROFIT_TO_LOSS:
        for bad_phrase in _PROFIT_TO_LOSS_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_phrase) + r"\b", text_lower):
                return bad_phrase
    elif trend_state == TrendState.GAIN_TO_LOSS:
        for bad_word in _GAIN_TO_LOSS_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.LOSS_TO_GAIN:
        for bad_word in _LOSS_TO_GAIN_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.DEFICIT_WIDENED:
        for bad_word in _DEFICIT_WIDENED_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.DEFICIT_NARROWED:
        for bad_word in _DEFICIT_NARROWED_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.TURNED_POSITIVE:
        for bad_word in _TURNED_POSITIVE_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.TURNED_NEGATIVE:
        for bad_word in _TURNED_NEGATIVE_REPLACEMENTS:
            if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                return bad_word
    elif trend_state == TrendState.INCREASED:
        if family == MetricSemanticFamily.CASH_FLOW:
            for bad_word in _CASH_FLOW_INCREASE_REPLACEMENTS:
                if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                    return bad_word
        elif family == MetricSemanticFamily.EXPENSE:
            for bad_word in _EXPENSE_INCREASE_REPLACEMENTS:
                if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                    return bad_word
        else:
            for bad_word in _STANDARD_INCREASE_REPLACEMENTS:
                if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                    return bad_word
    elif trend_state == TrendState.DECREASED:
        if family == MetricSemanticFamily.EXPENSE:
            for bad_word in _EXPENSE_DECREASE_REPLACEMENTS:
                if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                    return bad_word
        else:
            for bad_word in _STANDARD_DECREASE_REPLACEMENTS:
                if re.search(r"\b" + re.escape(bad_word) + r"\b", text_lower):
                    return bad_word

    return None


def split_into_clauses(text: str) -> list[str]:
    r"""Split slide text into local clauses / claim spans.

    Splits on:
    - Newlines, semicolons, em/en dashes
    - Periods not within numbers ((?<!\d)\.(?!\d)\s+)
    - Contrastive / coordinating conjunctions (while, whilst, whereas, although, though, but, however, yet)
    - Comma followed by conjunction or word boundary (not within numbers like '1,121')
    """
    delims = [
        r"\r?\n+",
        r";\s*",
        r"\s+[—–]\s+",
        r"(?<!\d)\.(?!\d)\s+",
        r",\s+(?:while|whilst|whereas|although|though|but|however|yet|and)\b",
        r"\b(?:while|whilst|whereas|although|though|but|however|yet)\b",
        r"(?<!\d),(?!\d)\s+(?=[a-zA-Z])",
    ]
    pattern = "|".join(delims)
    raw_clauses = re.split(pattern, text, flags=re.IGNORECASE)
    return [c.strip() for c in raw_clauses if c and c.strip()]


def extract_metric_aliases(
    metric_name: str,
    canonical_name: str | None = None,
    pres_label: str | None = None,
) -> list[str]:
    """Extract canonical and presentation aliases for a metric, rejecting single generic tokens."""
    aliases: set[str] = set()

    clean_metric = metric_name.strip()
    if clean_metric:
        aliases.add(clean_metric)
        no_punct = re.sub(r"[_\-]+", " ", clean_metric).strip()
        if no_punct:
            aliases.add(no_punct)
        no_parens = re.sub(r"\s*\(.*?\)", "", no_punct).strip()
        if no_parens:
            aliases.add(no_parens)

    if canonical_name:
        clean_can = canonical_name.strip()
        aliases.add(clean_can)
        can_words = clean_can.replace("_", " ").strip()
        if can_words:
            aliases.add(can_words)

    if pres_label:
        clean_pres = pres_label.strip()
        if clean_pres:
            aliases.add(clean_pres)
            aliases.add(re.sub(r"[_\-]+", " ", clean_pres).strip())

    combined = f"{canonical_name or ''} {metric_name} {pres_label or ''}".casefold()

    if any(k in combined for k in ("gross profit margin", "gross margin", "gross profit as % of revenue", "gp margin", "gross_margin", "gross_profit_margin")):
        aliases.update(["gross profit margin", "gross margin", "gp margin", "gross margins", "毛利率"])
    elif any(k in combined for k in ("revenue", "turnover", "top line", "topline")) and not any(k in combined for k in ("gross profit as %", "margin", "/ revenue", "% of revenue", "share of revenue")):
        aliases.update(["revenue", "total revenue", "turnover", "top line", "topline", "营业收入", "收入"])

    if "redemption" in combined and "liabilit" in combined:
        aliases.update(["redemption liabilities", "redemption liability", "liabilities for redemption"])

    if "operating cash" in combined or "cash from operations" in combined or "cash flow from operating" in combined:
        aliases.update(["operating cash flow", "cash from operations", "operating cash flows", "operating cash", "经营活动现金流", "经营现金流"])
    elif "cash" in combined and not any(k in combined for k in ("cash flow", "operating cash", "investing cash", "financing cash")):
        aliases.update(["cash and cash equivalents", "cash balance", "cash reserves", "cash", "现金及现金等价物", "现金余额", "现金"])

    if "net loss" in combined or "net_loss" in combined or "adjusted net loss" in combined:
        aliases.update(["net loss", "net losses", "adjusted net loss", "adjusted net losses", "loss for the year", "loss for the period", "净亏损"])
    elif "operating loss" in combined or "operating_loss" in combined:
        aliases.update(["operating loss", "operating losses", "营业亏损"])

    if is_signed_gain_loss_metric(metric_name, canonical_name):
        aliases.update([
            "net foreign exchange gain/(loss)",
            "net foreign exchange gain/loss",
            "foreign exchange gain/(loss)",
            "foreign exchange gain/loss",
            "fx gain/(loss)",
            "fx gain/loss",
            "foreign exchange gain",
            "foreign exchange loss",
            "fx gain",
            "fx loss",
            "fair value gain/(loss)",
            "fair value gain/loss",
        ])

    if any(k in combined for k in ("net current liabilities", "net current liability")):
        aliases.update(["net current liabilities", "net current liability", "流动负债净额"])

    if any(k in combined for k in ("depreciation", "amortization")):
        aliases.update(["depreciation and amortization", "depreciation & amortization", "d&a", "depreciation", "amortization"])

    if any(k in combined for k in ("employee benefit", "staff cost")):
        aliases.update(["employee benefit expenses", "employee benefits", "employee benefit expense", "staff costs", "staff cost"])

    filtered: set[str] = set()
    is_multi_word = len(clean_metric.split()) > 1 or (canonical_name and "_" in canonical_name)
    generic_isolated_tokens = {"revenue", "profit", "loss", "cash", "expense", "expenses", "cost", "costs", "margin", "ratio"}

    for a in aliases:
        a_clean = a.strip()
        if not a_clean or len(a_clean) < 2:
            continue
        if is_multi_word and a_clean.casefold() in generic_isolated_tokens:
            if a_clean.casefold() == "cash" and "cash and cash equivalents" in combined:
                filtered.add(a_clean)
            elif a_clean.casefold() == "revenue" and "total revenue" in combined:
                filtered.add(a_clean)
            else:
                continue
        else:
            filtered.add(a_clean)

    return sorted(filtered, key=lambda s: -len(s))


_ALL_DIRECTIONAL_WORDS: list[str] = [
    "turned profitable", "reversed from loss to profit",
    "swung into loss", "reversed from profit to loss", "reversal to loss",
    "turned positive", "turned negative",
    "swung from gain to loss", "swung from loss to gain",
    "cash outflow narrowed", "cash outflow widened",
    "loss narrowed", "loss widening", "loss widened", "loss narrowing",
    "increased", "increasing", "increases", "increase",
    "declined", "declining", "declines", "decline",
    "decreased", "decreasing", "decreases", "decrease",
    "fell", "falling", "falls", "fall",
    "dropped", "dropping", "drops", "drop",
    "contracted", "contracting", "contraction",
    "expanded", "expanding", "expansion",
    "narrowed", "narrowing", "narrows", "narrow",
    "widened", "widening", "widens", "widen",
    "grew", "growing", "grow", "growth",
    "rose", "rising", "rises", "rise",
    "surged", "surging",
    "improved", "improving", "improvement",
    "deteriorated", "deteriorating", "deterioration",
    "slumped",
]
_ALL_DIRECTIONAL_WORDS.sort(key=lambda w: -len(w))


def associate_clause_directions(
    clause: str,
    metric_aliases_map: dict[str, list[str]],
    metric_values_map: dict[str, list[str]] | None = None,
    is_only_metric: bool = False,
    only_metric_name: str | None = None,
) -> list[tuple[str, str]]:
    """Find directional claims in a local clause and associate each only with its specific metric."""
    all_alias_pairs: list[tuple[int, str, str]] = []
    for m_name, aliases in metric_aliases_map.items():
        for alias in aliases:
            all_alias_pairs.append((len(alias), alias, m_name))
    all_alias_pairs.sort(key=lambda x: -x[0])

    clause_lower = clause.casefold()
    occupied = [False] * len(clause)
    metric_spans: list[tuple[int, int, str]] = []
    for _, alias, m_name in all_alias_pairs:
        pattern = r"\b" + re.escape(alias.casefold()) + r"\b"
        for m in re.finditer(pattern, clause_lower):
            s, e = m.start(), m.end()
            if not any(occupied[s:e]):
                metric_spans.append((s, e, m_name))
                for i in range(s, e):
                    occupied[i] = True

    metric_spans.sort(key=lambda x: x[0])

    # Find directional words/phrases
    dir_spans: list[tuple[int, int, str]] = []
    occupied_dir = [False] * len(clause)
    for dw in _ALL_DIRECTIONAL_WORDS:
        pattern = r"\b" + re.escape(dw.casefold()) + r"\b"
        for m in re.finditer(pattern, clause_lower):
            s, e = m.start(), m.end()
            if not any(occupied_dir[s:e]):
                dir_spans.append((s, e, dw))
                for i in range(s, e):
                    occupied_dir[i] = True

    dir_spans.sort(key=lambda x: x[0])

    if not dir_spans:
        return []

    # If no metric name matched in clause, check if specific values match
    if not metric_spans and metric_values_map:
        for m_name, vals in metric_values_map.items():
            for v_str in vals:
                if v_str and len(v_str) >= 2 and re.search(r"\b" + re.escape(v_str) + r"\b", clause_lower):
                    metric_spans.append((0, len(clause), m_name))
                    break

    if not metric_spans:
        if is_only_metric and only_metric_name:
            return [(only_metric_name, dw) for _, _, dw in dir_spans]
        return []

    if len(metric_spans) == 1:
        m_name = metric_spans[0][2]
        return [(m_name, dw) for _, _, dw in dir_spans]

    # Multiple metrics in clause: associate each directional word with closest metric span
    assocs: list[tuple[str, str]] = []
    for ds, de, dw in dir_spans:
        closest_m = None
        min_dist = 999999
        for ms, me, m_name in metric_spans:
            if de <= ms:
                dist = ms - de
            elif me <= ds:
                dist = ds - me
            else:
                dist = 0
            if dist < min_dist:
                min_dist = dist
                closest_m = m_name
        if closest_m:
            assocs.append((closest_m, dw))
    return assocs


def is_text_relevant_to_metric(
    text: str,
    metric_name: str,
    val_start: float,
    val_end: float,
    is_only_metric: bool,
) -> bool:
    """Check whether a specific slide component relates to a metric."""
    if is_only_metric:
        return True
    aliases = extract_metric_aliases(metric_name)
    text_lower = text.casefold()
    if any(re.search(r"\b" + re.escape(a.casefold()) + r"\b", text_lower) for a in aliases):
        return True
    s_start = str(round(val_start, 2)).rstrip("0").rstrip(".")
    s_end = str(round(val_end, 2)).rstrip("0").rstrip(".")
    if (s_start in text_lower and s_start not in ("", "0")) or (s_end in text_lower and s_end not in ("", "0")):
        return True
    return False


class ClaimValidator:
    """Validates directional and numeric claims across presentation slides."""

    def __init__(self, relative_tolerance: float = 0.10) -> None:
        self.relative_tolerance = relative_tolerance

    def validate_plan(
        self,
        plan: PresentationPlan,
        observations: list[Observation],
    ) -> list[ValidationIssue]:
        """Validate entire presentation plan and return structured ValidationIssues."""
        issues: list[ValidationIssue] = []
        obs_by_id = {obs.id: obs for obs in observations}

        for slide in plan.slides:
            # 1. Slide-type scoping: skip non-analytical slide types
            if slide.slide_type in (
                "cover",
                "contents",
                "data_quality",
                "appendix",
                "section_divider",
                "divider",
            ):
                continue

            slide_obs = [obs_by_id[oid] for oid in slide.observation_ids if oid in obs_by_id]
            for block in getattr(slide, "visual_blocks", []):
                for oid in getattr(block, "observation_ids", []):
                    if oid in obs_by_id and obs_by_id[oid] not in slide_obs:
                        slide_obs.append(obs_by_id[oid])

            # 2. Remove global observation fallback:
            # If a slide has no linked observations, skip numeric directional validation
            if not slide_obs:
                continue

            # 3. For company_overview, validate only if linked observations exist AND narrative claims are present
            if slide.slide_type == "company_overview":
                full_text = " ".join([slide.title, slide.message, *slide.bullets])
                has_claim = any(
                    re.search(r"\b" + re.escape(w) + r"\b", full_text, flags=re.IGNORECASE)
                    for w in _ALL_DIRECTIONAL_WORDS
                )
                if not has_claim:
                    continue

            slide_issues = self.validate_slide(slide, slide_obs)
            issues.extend(slide_issues)

        return issues

    def validate_slide(
        self,
        slide: PresentationSlide,
        observations: list[Observation],
    ) -> list[ValidationIssue]:
        """Validate a single slide against observations, returning structured DirectionalClaimIssue objects."""
        issues: list[ValidationIssue] = []

        by_metric: dict[str, list[Observation]] = {}
        for obs in observations:
            if obs.value is None or not obs.period:
                continue
            key = (obs.metric_canonical or obs.metric_original).strip().casefold()
            by_metric.setdefault(key, []).append(obs)

        if not by_metric:
            return issues

        metric_info: dict[str, dict[str, Any]] = {}
        metric_aliases_map: dict[str, list[str]] = {}
        metric_values_map: dict[str, list[str]] = {}

        for metric_name, obs_list in by_metric.items():
            if len(obs_list) < 2:
                continue
            sorted_obs = sorted(obs_list, key=lambda o: period_sort_key(o.period))
            first = sorted_obs[0]
            last = sorted_obs[-1]

            val_start = float(first.value)
            val_end = float(last.value)

            is_comp, comp_reason = are_observations_compatible(first, last)
            family = classify_metric_semantic_family(metric_name, canonical_name=first.metric_canonical)
            bs_subtype = (
                classify_balance_sheet_subtype(metric_name, canonical_name=first.metric_canonical)
                if family == MetricSemanticFamily.BALANCE_SHEET
                else BalanceSheetSubtype.STANDARD
            )

            if is_comp:
                trend_state = determine_trend_state(
                    metric_name,
                    val_start,
                    val_end,
                    canonical_name=first.metric_canonical,
                )
            else:
                trend_state = None

            aliases = extract_metric_aliases(
                metric_name,
                canonical_name=first.metric_canonical,
                pres_label=getattr(first, "presentation_label", None),
            )
            metric_aliases_map[metric_name] = aliases

            vals = []
            s_s = str(round(val_start, 2)).rstrip("0").rstrip(".")
            s_e = str(round(val_end, 2)).rstrip("0").rstrip(".")
            if s_s and s_s != "0":
                vals.append(s_s)
            if s_e and s_e != "0":
                vals.append(s_e)
            metric_values_map[metric_name] = vals

            metric_info[metric_name] = {
                "first": first,
                "last": last,
                "val_start": val_start,
                "val_end": val_end,
                "is_comp": is_comp,
                "comp_reason": comp_reason,
                "family": family,
                "bs_subtype": bs_subtype,
                "trend_state": trend_state,
            }

        if not metric_info:
            return issues

        is_only_metric = len(metric_info) == 1
        only_metric_name = next(iter(metric_info)) if is_only_metric else None

        components = [
            ("title", slide.title, None),
            ("message", slide.message, None),
            *[(f"bullet", bullet, idx) for idx, bullet in enumerate(slide.bullets)],
        ]

        seen_issues: set[tuple[str, str, int | None, str]] = set()

        for comp_type, comp_text, bullet_idx in components:
            if not comp_text.strip():
                continue

            # Check if component mentions an ambiguous-sign metric
            for m_name, info in metric_info.items():
                if info["trend_state"] == TrendState.AMBIGUOUS:
                    aliases = metric_aliases_map.get(m_name, [])
                    mentioned = any(re.search(r"\b" + re.escape(a.casefold()) + r"\b", comp_text.casefold()) for a in aliases) or is_only_metric
                    if mentioned:
                        issue_key = (m_name, comp_type, bullet_idx, "ambiguous_semantics")
                        if issue_key not in seen_issues:
                            seen_issues.add(issue_key)
                            issues.append(
                                DirectionalClaimIssue(
                                    code="directional_contradiction",
                                    message=(
                                        f"Slide {slide.id} has ambiguous sign semantics for metric '{m_name}' "
                                        f"transitioning from {info['val_start']} to {info['val_end']}. Export blocked."
                                    ),
                                    severity="error",
                                    stage="presentation",
                                    slide_id=slide.id,
                                    metric_name=m_name,
                                    semantic_family=info["family"].value,
                                    balance_sheet_subtype=info["bs_subtype"].value,
                                    related_ids=[info["first"].id, info["last"].id],
                                    start_value=info["val_start"],
                                    end_value=info["val_end"],
                                    expected_direction=TrendState.AMBIGUOUS.value,
                                    offending_direction="ambiguous_semantics",
                                    target_component=comp_type,
                                    bullet_index=bullet_idx,
                                )
                            )

            clauses = split_into_clauses(comp_text)
            for clause in clauses:
                assocs = associate_clause_directions(
                    clause,
                    metric_aliases_map,
                    metric_values_map,
                    is_only_metric=is_only_metric,
                    only_metric_name=only_metric_name,
                )

                for m_name, dir_word in assocs:
                    if m_name not in metric_info:
                        continue
                    info = metric_info[m_name]
                    first = info["first"]
                    last = info["last"]
                    val_start = info["val_start"]
                    val_end = info["val_end"]
                    is_comp = info["is_comp"]
                    comp_reason = info["comp_reason"]
                    family = info["family"]
                    bs_subtype = info["bs_subtype"]
                    trend_state = info["trend_state"]

                    issue_key = (m_name, comp_type, bullet_idx, dir_word.casefold())
                    if issue_key in seen_issues:
                        continue

                    if not is_comp:
                        seen_issues.add(issue_key)
                        issues.append(
                            DirectionalClaimIssue(
                                code="directional_contradiction",
                                message=(
                                    f"Slide {slide.id} asserts directional movement '{dir_word}' for '{m_name}', "
                                    f"but observations are incompatible: {comp_reason}. Export blocked."
                                ),
                                severity="error",
                                stage="presentation",
                                slide_id=slide.id,
                                metric_name=m_name,
                                semantic_family=family.value,
                                balance_sheet_subtype=bs_subtype.value,
                                related_ids=[first.id, last.id],
                                start_value=val_start,
                                end_value=val_end,
                                expected_direction="INCOMPATIBLE",
                                offending_direction=dir_word,
                                target_component=comp_type,
                                bullet_index=bullet_idx,
                            )
                        )
                        continue

                    if trend_state == TrendState.AMBIGUOUS:
                        seen_issues.add(issue_key)
                        issues.append(
                            DirectionalClaimIssue(
                                code="directional_contradiction",
                                message=(
                                    f"Slide {slide.id} has ambiguous sign semantics for metric '{m_name}' "
                                    f"transitioning from {val_start} to {val_end}. Export blocked."
                                ),
                                severity="error",
                                stage="presentation",
                                slide_id=slide.id,
                                metric_name=m_name,
                                semantic_family=family.value,
                                balance_sheet_subtype=bs_subtype.value,
                                related_ids=[first.id, last.id],
                                start_value=val_start,
                                end_value=val_end,
                                expected_direction=TrendState.AMBIGUOUS.value,
                                offending_direction=dir_word,
                                target_component=comp_type,
                                bullet_index=bullet_idx,
                            )
                        )
                        continue

                    offending = _detect_offending_in_text(dir_word, trend_state, family)
                    if offending:
                        seen_issues.add(issue_key)
                        verb = (
                            "narrowed" if trend_state in (TrendState.LOSS_NARROWED, TrendState.DEFICIT_NARROWED)
                            else "widened" if trend_state in (TrendState.LOSS_WIDENED, TrendState.DEFICIT_WIDENED)
                            else "turned profitable" if trend_state == TrendState.LOSS_TO_PROFIT
                            else "swung into loss" if trend_state == TrendState.PROFIT_TO_LOSS
                            else "swung from gain to loss" if trend_state == TrendState.GAIN_TO_LOSS
                            else "swung from loss to gain" if trend_state == TrendState.LOSS_TO_GAIN
                            else "turned positive" if trend_state == TrendState.TURNED_POSITIVE
                            else "turned negative" if trend_state == TrendState.TURNED_NEGATIVE
                            else "cash outflow narrowed / increased" if (trend_state == TrendState.INCREASED and family == MetricSemanticFamily.CASH_FLOW)
                            else "increased" if trend_state == TrendState.INCREASED
                            else "decreased" if trend_state == TrendState.DECREASED
                            else "held flat"
                        )
                        issues.append(
                            DirectionalClaimIssue(
                                code="directional_contradiction",
                                message=(
                                    f"Slide {slide.id} {comp_type} asserts '{offending}' for '{m_name}', "
                                    f"but underlying values {verb} from {val_start} to {val_end} ({trend_state.value})."
                                ),
                                severity="error",
                                stage="presentation",
                                slide_id=slide.id,
                                metric_name=m_name,
                                semantic_family=family.value,
                                balance_sheet_subtype=bs_subtype.value,
                                related_ids=[first.id, last.id],
                                start_value=val_start,
                                end_value=val_end,
                                expected_direction=trend_state.value,
                                offending_direction=offending,
                                target_component=comp_type,
                                bullet_index=bullet_idx,
                            )
                        )

        return issues

    def validate_slide_claims(
        self,
        slide_id: str,
        claim_text: str,
        observations: list[Observation],
    ) -> list[ValidationIssue]:
        """Backward-compatible validation helper for plain text."""
        slide = PresentationSlide(
            id=slide_id,
            slide_type="analysis",
            title=claim_text,
        )
        return self.validate_slide(slide, observations)


def apply_structured_issue_replacement(text: str, issue: DirectionalClaimIssue) -> tuple[str, bool]:
    """Replace the offending direction in text using the expected trend state and semantic family."""
    state = issue.expected_direction
    offending = issue.offending_direction
    family = issue.semantic_family

    replacement = None

    if state == TrendState.GAIN_TO_LOSS.value:
        replacement = _GAIN_TO_LOSS_REPLACEMENTS.get(offending.casefold(), "swung from gain to loss")
    elif state == TrendState.LOSS_TO_GAIN.value:
        replacement = _LOSS_TO_GAIN_REPLACEMENTS.get(offending.casefold(), "swung from loss to gain")
    elif state == TrendState.TURNED_POSITIVE.value:
        replacement = _TURNED_POSITIVE_REPLACEMENTS.get(offending.casefold(), "turned positive")
    elif state == TrendState.TURNED_NEGATIVE.value:
        replacement = _TURNED_NEGATIVE_REPLACEMENTS.get(offending.casefold(), "turned negative")
    elif state == TrendState.LOSS_TO_PROFIT.value:
        replacement = _LOSS_TO_PROFIT_REPLACEMENTS.get(offending.casefold(), "turned profitable")
    elif state == TrendState.PROFIT_TO_LOSS.value:
        replacement = _PROFIT_TO_LOSS_REPLACEMENTS.get(offending.casefold(), "swung into loss")
    elif state == TrendState.LOSS_NARROWED.value:
        replacement = _LOSS_NARROWED_REPLACEMENTS.get(offending.casefold(), "narrowed")
    elif state == TrendState.LOSS_WIDENED.value:
        replacement = _LOSS_WIDENED_REPLACEMENTS.get(offending.casefold(), "widened")
    elif state == TrendState.DEFICIT_WIDENED.value:
        replacement = _DEFICIT_WIDENED_REPLACEMENTS.get(offending.casefold(), "widened")
    elif state == TrendState.DEFICIT_NARROWED.value:
        replacement = _DEFICIT_NARROWED_REPLACEMENTS.get(offending.casefold(), "narrowed")
    elif state == TrendState.INCREASED.value:
        if family == MetricSemanticFamily.CASH_FLOW.value:
            replacement = _CASH_FLOW_INCREASE_REPLACEMENTS.get(offending.casefold(), "increased")
        elif family == MetricSemanticFamily.EXPENSE.value:
            replacement = _EXPENSE_INCREASE_REPLACEMENTS.get(offending.casefold(), "increased")
        else:
            replacement = _STANDARD_INCREASE_REPLACEMENTS.get(offending.casefold(), "increased")
    elif state == TrendState.DECREASED.value:
        if family == MetricSemanticFamily.EXPENSE.value:
            replacement = _EXPENSE_DECREASE_REPLACEMENTS.get(offending.casefold(), "decreased")
        else:
            replacement = _STANDARD_DECREASE_REPLACEMENTS.get(offending.casefold(), "decreased")
    else:
        return text, False

    if not replacement:
        return text, False

    # Safety guard: for non-profit/loss metrics, NEVER generate loss words
    if family != MetricSemanticFamily.PROFIT_LOSS.value:
        for bad_p in _FORBIDDEN_NON_PROFIT_LOSS_PHRASES:
            if bad_p in replacement.casefold():
                replacement = "increased" if state == TrendState.INCREASED.value else "decreased"

    # Clause-aware replacement: find the specific clause mentioning issue.metric_name
    delims = r"(\r?\n+|;\s*|\s+[—–]\s+|(?<!\d)\.(?!\d)\s+|,\s*(?:while|whilst|whereas|although|though|but|however|yet)\b|\b(?:while|whilst|whereas|although|though|but|however|yet)\b|(?<!\d),(?!\d)\s+(?=[a-zA-Z]))"
    parts = re.split(delims, text, flags=re.IGNORECASE)
    metric_aliases = extract_metric_aliases(issue.metric_name)

    replaced = False
    new_parts = []
    alias_patterns = [r"\b" + re.escape(a.casefold()) + r"\b" for a in metric_aliases]
    for p in parts:
        if not replaced and any(re.search(pat, p.casefold()) for pat in alias_patterns):
            pat_off = r"\b" + re.escape(offending) + r"\b"
            if re.search(pat_off, p, flags=re.IGNORECASE):
                p, replaced = replace_word_preserving_case(p, offending, replacement)
        new_parts.append(p)

    if replaced:
        return "".join(new_parts), True

    # Fallback to general replace if metric was not isolated in a single clause
    return replace_word_preserving_case(text, offending, replacement)


def repair_presentation_plan_from_issues(
    plan: PresentationPlan,
    issues: list[ValidationIssue],
) -> tuple[PresentationPlan, list[str]]:
    """Directly repair presentation plan using structured DirectionalClaimIssue records."""
    repairs: list[str] = []
    slide_by_id = {s.id: s for s in plan.slides}

    for issue in issues:
        if not isinstance(issue, DirectionalClaimIssue):
            continue
        if issue.expected_direction in (TrendState.AMBIGUOUS.value, "INCOMPATIBLE", TrendState.FLAT.value):
            # Unsafe or ambiguous: do not repair, keep blocked
            continue

        slide = slide_by_id.get(issue.slide_id)
        if not slide:
            continue

        if issue.target_component == "title":
            repaired, changed = apply_structured_issue_replacement(slide.title, issue)
            if changed:
                slide.title = repaired
                repairs.append(
                    f"Slide {slide.id} title: replaced '{issue.offending_direction}' for '{issue.metric_name}' ({issue.expected_direction})"
                )
        elif issue.target_component == "message":
            repaired, changed = apply_structured_issue_replacement(slide.message, issue)
            if changed:
                slide.message = repaired
                repairs.append(
                    f"Slide {slide.id} message: replaced '{issue.offending_direction}' for '{issue.metric_name}' ({issue.expected_direction})"
                )
        elif issue.target_component == "bullet" and issue.bullet_index is not None:
            if 0 <= issue.bullet_index < len(slide.bullets):
                repaired, changed = apply_structured_issue_replacement(slide.bullets[issue.bullet_index], issue)
                if changed:
                    slide.bullets[issue.bullet_index] = repaired
                    repairs.append(
                        f"Slide {slide.id} bullet #{issue.bullet_index+1}: replaced '{issue.offending_direction}' for '{issue.metric_name}' ({issue.expected_direction})"
                    )

    return plan, repairs


def repair_slide_claims(
    slide: PresentationSlide,
    observations: list[Observation],
) -> tuple[PresentationSlide, list[str]]:
    """Backward-compatible slide repair using ClaimValidator structured issues."""
    validator = ClaimValidator()
    issues = validator.validate_slide(slide, observations)
    plan = PresentationPlan(title="Temp", slides=[slide])
    repaired_plan, repairs = repair_presentation_plan_from_issues(plan, issues)
    return repaired_plan.slides[0], repairs


def repair_presentation_plan(
    plan: PresentationPlan,
    observations: list[Observation],
) -> tuple[PresentationPlan, list[str]]:
    """Execute claim repairs across all slides using structured validation issues."""
    validator = ClaimValidator()
    issues = validator.validate_plan(plan, observations)
    return repair_presentation_plan_from_issues(plan, issues)


