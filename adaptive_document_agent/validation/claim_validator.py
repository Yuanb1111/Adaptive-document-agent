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


def is_text_relevant_to_metric(
    text: str,
    metric_name: str,
    val_start: float,
    val_end: float,
    is_only_metric: bool,
) -> bool:
    """Check whether a specific slide component (title, message, bullet) relates to a metric."""
    if is_only_metric:
        return True
    text_lower = text.casefold()
    tokens = [t for t in re.findall(r"[a-z0-9]+", metric_name) if len(t) > 2 and t not in ("and", "the", "for", "with", "expense", "expenses")]
    if any(t in text_lower for t in tokens):
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
            slide_obs = [obs_by_id[oid] for oid in slide.observation_ids if oid in obs_by_id]
            for block in getattr(slide, "visual_blocks", []):
                for oid in getattr(block, "observation_ids", []):
                    if oid in obs_by_id and obs_by_id[oid] not in slide_obs:
                        slide_obs.append(obs_by_id[oid])

            effective_obs = slide_obs if slide_obs else observations
            slide_issues = self.validate_slide(slide, effective_obs)
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

        is_only_metric = len(by_metric) == 1

        for metric_name, obs_list in by_metric.items():
            if len(obs_list) < 2:
                continue
            sorted_obs = sorted(obs_list, key=lambda o: period_sort_key(o.period))
            first = sorted_obs[0]
            last = sorted_obs[-1]

            val_start = float(first.value)
            val_end = float(last.value)

            # Check compatibility
            is_comp, comp_reason = are_observations_compatible(first, last)

            # Classify semantic family first
            family = classify_metric_semantic_family(metric_name, canonical_name=first.metric_canonical)
            bs_subtype = (
                classify_balance_sheet_subtype(metric_name, canonical_name=first.metric_canonical)
                if family == MetricSemanticFamily.BALANCE_SHEET
                else BalanceSheetSubtype.STANDARD
            )

            # Determine trend state
            if is_comp:
                trend_state = determine_trend_state(
                    metric_name,
                    val_start,
                    val_end,
                    canonical_name=first.metric_canonical,
                )
            else:
                trend_state = TrendState.AMBIGUOUS

            # Check each text component on the slide
            components = [
                ("title", slide.title, None),
                ("message", slide.message, None),
                *[(f"bullet", bullet, idx) for idx, bullet in enumerate(slide.bullets)],
            ]

            for comp_type, comp_text, bullet_idx in components:
                if not comp_text.strip():
                    continue
                if not is_text_relevant_to_metric(comp_text, metric_name, val_start, val_end, is_only_metric):
                    continue

                if not is_comp:
                    # Slide asserts directional claims on incompatible observations
                    offending = any(
                        w in comp_text.casefold()
                        for w in (
                            "increased", "decreased", "declined", "narrowed", "widened",
                            "improved", "deteriorated", "grew", "rose", "fell", "contracted"
                        )
                    )
                    if offending:
                        issues.append(
                            DirectionalClaimIssue(
                                code="directional_contradiction",
                                message=(
                                    f"Slide {slide.id} asserts directional movement for '{metric_name}', "
                                    f"but observations are incompatible: {comp_reason}. Export blocked."
                                ),
                                severity="error",
                                stage="presentation",
                                slide_id=slide.id,
                                metric_name=metric_name,
                                semantic_family=family.value,
                                balance_sheet_subtype=bs_subtype.value,
                                related_ids=[first.id, last.id],
                                start_value=val_start,
                                end_value=val_end,
                                expected_direction="INCOMPATIBLE",
                                offending_direction=comp_text[:30],
                                target_component=comp_type,
                                bullet_index=bullet_idx,
                            )
                        )
                    continue

                if trend_state == TrendState.AMBIGUOUS:
                    # Ambiguous sign semantics: block export instead of guessing
                    issues.append(
                        DirectionalClaimIssue(
                            code="directional_contradiction",
                            message=(
                                f"Slide {slide.id} has ambiguous sign semantics for metric '{metric_name}' "
                                f"transitioning from {val_start} to {val_end}. Export blocked."
                            ),
                            severity="error",
                            stage="presentation",
                            slide_id=slide.id,
                            metric_name=metric_name,
                            semantic_family=family.value,
                            balance_sheet_subtype=bs_subtype.value,
                            related_ids=[first.id, last.id],
                            start_value=val_start,
                            end_value=val_end,
                            expected_direction=TrendState.AMBIGUOUS.value,
                            offending_direction="ambiguous_semantics",
                            target_component=comp_type,
                            bullet_index=bullet_idx,
                        )
                    )
                    continue

                # Check for offending direction
                offending_word = _detect_offending_in_text(comp_text, trend_state, family)
                if offending_word:
                    verb = (
                        "narrowed" if trend_state in (TrendState.LOSS_NARROWED, TrendState.DEFICIT_NARROWED)
                        else "widened" if trend_state in (TrendState.LOSS_WIDENED, TrendState.DEFICIT_WIDENED)
                        else "turned profitable" if trend_state == TrendState.LOSS_TO_PROFIT
                        else "swung into loss" if trend_state == TrendState.PROFIT_TO_LOSS
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
                                f"Slide {slide.id} {comp_type} asserts '{offending_word}' for '{metric_name}', "
                                f"but underlying values {verb} from {val_start} to {val_end} ({trend_state.value})."
                            ),
                            severity="error",
                            stage="presentation",
                            slide_id=slide.id,
                            metric_name=metric_name,
                            semantic_family=family.value,
                            balance_sheet_subtype=bs_subtype.value,
                            related_ids=[first.id, last.id],
                            start_value=val_start,
                            end_value=val_end,
                            expected_direction=trend_state.value,
                            offending_direction=offending_word,
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

    if state == TrendState.TURNED_POSITIVE.value:
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


