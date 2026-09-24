"""Semantic topic alignment and metric matching for presentation slides.

Provides deterministic, generic topic classification and mismatch detection:
1. Direct metric aliases check in slide title/message/bullets.
2. Semantic topic groups:
   - Operating Expenses -> R&D, selling/distribution, administrative expenses, staff costs
   - Profitability / turned profitable -> profit, loss, net profit/loss, EBITDA, operating profit
   - Revenue -> revenue / turnover / sales
   - Liquidity -> cash, current assets/liabilities, working capital, current ratio
   - Debt / Leverage -> borrowings, total debt, leverage
3. Uses full slide context (title + section_title + message + bullets).
4. Only flags topic mismatches on positive evidence of a different topic.
5. Deduplicates mismatches per slide + metric family.
"""

from __future__ import annotations

import re
from typing import Any

from adaptive_document_agent.models.observation import Observation
from adaptive_document_agent.models.presentation import PresentationSlide


# ---------------------------------------------------------------------------
# 1. Topic Identifiers
# ---------------------------------------------------------------------------
TOPIC_REVENUE = "revenue"
TOPIC_PROFITABILITY = "profitability"
TOPIC_GROSS_PROFIT = "gross_profit"
TOPIC_NET_PROFIT = "net_profit"
TOPIC_EBITDA = "ebitda"
TOPIC_OPERATING_PROFIT = "operating_profit"

TOPIC_OPEX = "operating_expenses"
TOPIC_OPEX_RD = "rd_expenses"
TOPIC_OPEX_SELLING = "selling_expenses"
TOPIC_OPEX_ADMIN = "admin_expenses"
TOPIC_OPEX_STAFF = "staff_costs"

TOPIC_LIQUIDITY = "liquidity"
TOPIC_LIQUIDITY_CASH = "cash"
TOPIC_LIQUIDITY_RATIOS = "liquidity_ratios"
TOPIC_WORKING_CAPITAL = "working_capital"

TOPIC_DEBT = "debt"
TOPIC_CASH_FLOW = "cash_flow"
TOPIC_FINANCIAL_BROAD = "financial_broad"

# Topic hierarchy: Parent group -> set of all encompassed sub-topics
TOPIC_GROUPS: dict[str, set[str]] = {
    TOPIC_FINANCIAL_BROAD: {
        TOPIC_FINANCIAL_BROAD,
        TOPIC_REVENUE,
        TOPIC_PROFITABILITY,
        TOPIC_GROSS_PROFIT,
        TOPIC_NET_PROFIT,
        TOPIC_EBITDA,
        TOPIC_OPERATING_PROFIT,
        TOPIC_OPEX,
        TOPIC_OPEX_RD,
        TOPIC_OPEX_SELLING,
        TOPIC_OPEX_ADMIN,
        TOPIC_OPEX_STAFF,
        TOPIC_LIQUIDITY,
        TOPIC_LIQUIDITY_CASH,
        TOPIC_LIQUIDITY_RATIOS,
        TOPIC_WORKING_CAPITAL,
        TOPIC_DEBT,
        TOPIC_CASH_FLOW,
    },
    TOPIC_REVENUE: {TOPIC_REVENUE},
    TOPIC_PROFITABILITY: {
        TOPIC_PROFITABILITY,
        TOPIC_GROSS_PROFIT,
        TOPIC_NET_PROFIT,
        TOPIC_EBITDA,
        TOPIC_OPERATING_PROFIT,
    },
    TOPIC_OPEX: {
        TOPIC_OPEX,
        TOPIC_OPEX_RD,
        TOPIC_OPEX_SELLING,
        TOPIC_OPEX_ADMIN,
        TOPIC_OPEX_STAFF,
    },
    TOPIC_LIQUIDITY: {
        TOPIC_LIQUIDITY,
        TOPIC_LIQUIDITY_CASH,
        TOPIC_LIQUIDITY_RATIOS,
        TOPIC_WORKING_CAPITAL,
    },
    TOPIC_DEBT: {TOPIC_DEBT},
    TOPIC_CASH_FLOW: {TOPIC_CASH_FLOW},
}

# Sub-topic to parent group mapping
SUB_TO_PARENT: dict[str, str] = {}
for parent, subs in TOPIC_GROUPS.items():
    if parent == TOPIC_FINANCIAL_BROAD:
        continue
    for sub in subs:
        SUB_TO_PARENT[sub] = parent


# ---------------------------------------------------------------------------
# 2. Topic Detection Patterns
# ---------------------------------------------------------------------------
_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Specific OpEx sub-topics
    (TOPIC_OPEX_RD, re.compile(r"(?i)\b(research\s+(?:and|&)\s+development|r\s*&\s*d|rd\s+expenses?)\b")),
    (TOPIC_OPEX_SELLING, re.compile(r"(?i)\b(selling\s+(?:and|&)\s+distribution|selling\s+expenses?|distribution\s+expenses?|marketing\s+expenses?)\b")),
    (TOPIC_OPEX_ADMIN, re.compile(r"(?i)\b(administrative\s+expenses?|admin\s+expenses?|general\s+(?:and|&)\s+administrative|g\s*&\s*a)\b")),
    (TOPIC_OPEX_STAFF, re.compile(r"(?i)\b(staff\s+costs?|employee\s+benefits?|labor\s+costs?)\b")),
    # Aggregate OpEx
    (TOPIC_OPEX, re.compile(r"(?i)\b(operating\s+expenses?|operating\s+costs?|opex|operational\s+costs?|cost\s+structure|expenses?(\s+ratios?)?|cost\s+efficiency|operating\s+efficiency)\b")),

    # Specific Profitability sub-topics
    (TOPIC_EBITDA, re.compile(r"(?i)\b(adjusted\s+ebitda|ebitda)\b")),
    (TOPIC_GROSS_PROFIT, re.compile(r"(?i)\b(gross\s+profit|gross\s+margin|gp)\b")),
    (TOPIC_OPERATING_PROFIT, re.compile(r"(?i)\b(operating\s+profit|operating\s+income|operating\s+loss|ebit)\b")),
    (TOPIC_NET_PROFIT, re.compile(r"(?i)\b(net\s+profit|net\s+loss|profit\s+for\s+the|loss\s+for\s+the|net\s+income|profit\s+after\s+tax|loss\s+after\s+tax)\b")),
    # Aggregate Profitability (including margins & operating leverage)
    (TOPIC_PROFITABILITY, re.compile(r"(?i)\b(profitability|profitable|turned\s+profitable|turned\s+positive|turnaround|bottom-?line|net\s+turned\s+profitable|margins?|margin\s+trajectory|profit\s+margins?|operating\s+leverage)\b")),

    # Revenue
    (TOPIC_REVENUE, re.compile(r"(?i)\b(revenue|revenues|turnover|top-?line|sales|net\s+sales|contracted\s+sales|gross\s+revenue)\b")),

    # Liquidity & Working Capital
    (TOPIC_LIQUIDITY_CASH, re.compile(r"(?i)\b(cash\s+and\s+cash\s+equivalents|bank\s+balances?|cash\s+position|cash\s+balance)\b")),
    (TOPIC_LIQUIDITY_RATIOS, re.compile(r"(?i)\b(current\s+ratio|quick\s+ratio|cash\s+ratio)\b")),
    (TOPIC_WORKING_CAPITAL, re.compile(r"(?i)\b(working\s+capital|trade\s+receivables?|trade\s+payables?|inventor(?:y|ies)|current\s+assets?|current\s+liabilit(?:y|ies)|net\s+current\s+assets?|net\s+current\s+liabilit(?:y|ies))\b")),
    (TOPIC_LIQUIDITY, re.compile(r"(?i)\b(liquidity|solvency)\b")),

    # Debt & Capital Structure
    (TOPIC_DEBT, re.compile(r"(?i)\b(borrowings?|total\s+debt|net\s+debt|bank\s+loans?|leverage|gearing|capital\s+structure)\b")),

    # Cash flow
    (TOPIC_CASH_FLOW, re.compile(r"(?i)\b(cash\s+flows?|operating\s+cash\s+flows?|free\s+cash\s+flows?)\b")),

    # Broad financial overview / condition
    (TOPIC_FINANCIAL_BROAD, re.compile(r"(?i)\b(financial\s+performance|financial\s+overview|financial\s+results|financial\s+information|financial\s+highlights|financial\s+review|financial\s+condition|key\s+financials?|financial\s+summary|financial\s+data)\b")),
]


def extract_topics_from_text(text: str) -> set[str]:
    """Extract all recognized semantic topics from arbitrary text."""
    if not text:
        return set()
    topics: set[str] = set()
    for topic_id, pattern in _TOPIC_PATTERNS:
        if pattern.search(text):
            topics.add(topic_id)
            parent = SUB_TO_PARENT.get(topic_id)
            if parent:
                topics.add(parent)
    return topics


# ---------------------------------------------------------------------------
# 3. Direct Metric Aliases
# ---------------------------------------------------------------------------
def get_metric_name_variants(obs: Observation) -> list[str]:
    """Return normalized name variants and synonyms for an observation."""
    variants: list[str] = []
    for raw in [
        getattr(obs, "metric_original", ""),
        getattr(obs, "metric_canonical", ""),
        getattr(obs, "canonical_name", ""),
    ]:
        if raw and raw.strip():
            clean = raw.strip().casefold()
            variants.append(clean)
            # Add stripped punctuation variant
            stripped = re.sub(r"[\(\)/\\,\-_]", " ", clean).strip()
            stripped = re.sub(r"\s+", " ", stripped)
            if stripped and stripped != clean:
                variants.append(stripped)

    # Specific financial synonyms
    combined = " ".join(variants)
    if re.search(r"\b(revenue|turnover)\b", combined):
        variants.extend(["revenue", "revenues", "turnover", "sales"])
    if re.search(r"\b(research\s+and\s+development|r\s*&\s*d)\b", combined):
        variants.extend(["r&d", "r & d", "research & development", "research and development"])
    if re.search(r"\b(selling\s+and\s+distribution|selling)\b", combined):
        variants.extend(["selling and distribution", "selling & distribution", "selling expenses", "distribution expenses"])
    if re.search(r"\b(administrative|admin)\b", combined):
        variants.extend(["administrative expenses", "admin expenses", "general and administrative", "g&a"])
    if re.search(r"\b(ebitda)\b", combined):
        variants.extend(["ebitda", "adjusted ebitda"])
    if re.search(r"\b(loss|profit)\b", combined):
        variants.extend(["profit", "loss", "profitable", "net profit", "net loss", "turned profitable"])
        if "year" in combined or "period" in combined:
            variants.extend(["profit for the year", "loss for the year", "profit for the period", "loss for the period"])
    if re.search(r"\b(cash)\b", combined):
        variants.extend(["cash", "cash and cash equivalents", "bank balances"])
    if re.search(r"\b(current\s+ratio)\b", combined):
        variants.extend(["current ratio"])
    if re.search(r"\b(working\s+capital)\b", combined):
        variants.extend(["working capital"])

    return list(dict.fromkeys(variants))


def direct_metric_match(obs: Observation, text: str) -> bool:
    """Check if any variant of the observation's metric is directly referenced in text."""
    if not text:
        return False
    norm_text = text.casefold()
    norm_text_clean = re.sub(r"[\(\)/\\,\-_]", " ", norm_text)
    norm_text_clean = re.sub(r"\s+", " ", norm_text_clean)

    variants = get_metric_name_variants(obs)
    for variant in variants:
        # Check whole word match or phrase boundary
        pattern = rf"(?i)\b{re.escape(variant)}\b"
        if re.search(pattern, norm_text) or re.search(pattern, norm_text_clean):
            return True

    # Check composite phrase matches e.g. "Net Turned Profitable" -> (Loss)/profit for the year
    combined_m = " ".join(variants)
    if "profit" in combined_m or "loss" in combined_m:
        if re.search(r"(?i)\b(turned\s+profitable|net\s+turned\s+profitable|turned\s+positive)\b", norm_text):
            return True

    return False


# ---------------------------------------------------------------------------
# 4. Observation Topic Classification
# ---------------------------------------------------------------------------
def extract_observation_topics(obs: Observation) -> set[str]:
    """Identify which semantic topics an observation belongs to."""
    variants = get_metric_name_variants(obs)
    text = " ".join(variants)

    topics = extract_topics_from_text(text)

    # Categorize based on OpEx nature
    if any(t in topics for t in {TOPIC_OPEX_RD, TOPIC_OPEX_SELLING, TOPIC_OPEX_ADMIN, TOPIC_OPEX_STAFF}):
        topics.add(TOPIC_OPEX)

    # Categorize based on Profitability nature
    if any(t in topics for t in {TOPIC_NET_PROFIT, TOPIC_EBITDA, TOPIC_GROSS_PROFIT, TOPIC_OPERATING_PROFIT}):
        topics.add(TOPIC_PROFITABILITY)

    # Categorize based on Liquidity nature
    if any(t in topics for t in {TOPIC_LIQUIDITY_CASH, TOPIC_LIQUIDITY_RATIOS, TOPIC_WORKING_CAPITAL}):
        topics.add(TOPIC_LIQUIDITY)

    return topics


# ---------------------------------------------------------------------------
# 5. Token Extraction & Compatibility Check
# ---------------------------------------------------------------------------
_STOP_WORDS = {
    "and", "the", "a", "an", "is", "was", "are", "were", "for", "from", "to",
    "in", "of", "by", "at", "as", "during", "across", "with", "on", "about",
    "into", "through", "over", "under", "between", "against", "while",
    "key", "trajectory", "analysis", "trend", "trends", "overview", "reported",
    "evidence", "measures", "values", "summary", "executive", "deep", "dive",
    "performance", "results", "position", "highlights", "review", "indicators",
    "increased", "decreased", "rose", "fell", "declined", "grew", "growth",
    "widened", "narrowed", "improved", "deteriorated", "stable", "change",
    "changes", "movement", "movements", "turned", "scaled", "expanded", "contracted",
    "fiscal", "year", "period", "track", "record", "company", "group",
}


def extract_topic_tokens(text: str) -> set[str]:
    """Extract topic tokens from text without stripping financial metric keywords."""
    norm = text.casefold()
    norm = re.sub(r"\blosses\b", "loss", norm)
    strong_aliases = (
        (r"\bresearch\s+(?:and|&)\s+development\b|\br\s*&\s*d\b", "rdtopic"),
        (r"\bgross\s+profit\b", "grossprofit"),
        (r"\boperating\s+expenses?\b|\bopex\b", "opextopic"),
        (r"\bcurrent\s+liabilit(?:y|ies)\b", "currentliabilities"),
        (r"\bnet\s+(?:current\s+)?liabilit(?:y|ies)\b", "netliabilities"),
        (r"\btrade\s+(?:and\s+other\s+)?receivables?\b", "tradereceivables"),
        (r"\bselling\s+(?:and|&)\s+distribution\b", "sellingdistribution"),
        (r"\bworking\s+capital\b", "workingcapital"),
        (r"\bp\s*&\s*l\b", "pltopic"),
    )
    for pattern, alias in strong_aliases:
        norm = re.sub(pattern, alias, norm)

    tokens: set[str] = set()
    for token in re.findall(r"[^\W_]{2,}", norm):
        if token not in _STOP_WORDS and not any(char.isdigit() for char in token):
            tokens.add(token)
    return tokens


def get_slide_context(slide: PresentationSlide) -> str:
    """Aggregate all slide textual components (title, section_title, message, bullets)."""
    parts = [
        slide.title,
        getattr(slide, "section_title", None),
        getattr(slide, "message", None),
        *(getattr(slide, "bullets", None) or []),
    ]
    return " ".join(str(p).strip() for p in parts if p and str(p).strip())


def metrics_match_topic(
    obs: Observation,
    chart_canon: str,
    slide_title: str,
    slide_context: str | None = None,
) -> bool:
    """Deterministic check of whether an observation is compatible with the slide or chart topic."""
    obs_canon = (getattr(obs, "metric_canonical", "") or getattr(obs, "canonical_name", "") or "").strip().casefold()
    obs_name = (getattr(obs, "metric_original", "") or "").strip().casefold()

    # 1. Exact canonical or name match with chart_canon
    if chart_canon:
        c_norm = chart_canon.strip().casefold()
        if obs_canon == c_norm or obs_name == c_norm:
            return True
        # If chart_canon has specific alias match
        variants = get_metric_name_variants(obs)
        if c_norm in variants:
            return True

    full_context = f"{slide_title} {slide_context or ''}".strip()
    full_context = re.sub(r"\blosses\b", "loss", full_context, flags=re.I)

    # 2. Direct metric alias match in slide context
    if direct_metric_match(obs, full_context):
        return True

    # 3. Semantic topic groups alignment
    slide_topics = extract_topics_from_text(full_context)
    obs_topics = extract_observation_topics(obs)

    # Check if any slide topic matches any observation topic directly
    if slide_topics & obs_topics:
        return True

    # Check group inheritance (e.g. Slide is general TOPIC_OPEX, Obs is TOPIC_OPEX_RD)
    for s_topic in slide_topics:
        allowed = TOPIC_GROUPS.get(s_topic, {s_topic})
        if allowed & obs_topics:
            return True

    for o_topic in obs_topics:
        parent = SUB_TO_PARENT.get(o_topic)
        if parent and parent in slide_topics:
            return True

    # 4. Token overlap (preserving financial metric terms)
    title_tokens = extract_topic_tokens(full_context)
    obs_context = f"{obs_canon} {obs_name} {getattr(obs, 'entity', None) or ''} " + " ".join(
        str(v) for v in getattr(obs, "dimensions", {}).values()
    )
    obs_tokens = extract_topic_tokens(obs_context)
    if title_tokens and (title_tokens & obs_tokens):
        return True

    return False


def is_positive_topic_mismatch(
    obs: Observation,
    slide: PresentationSlide,
    *,
    is_supporting_kpi: bool = False,
) -> bool:
    """Return True ONLY if there is positive evidence that obs belongs to a different topic.

    Absence of token overlap alone is NOT sufficient for a critical mismatch.
    """
    full_context = get_slide_context(slide)

    # 1. If it matches directly or semantically, it's not a mismatch
    if metrics_match_topic(obs, "", slide.title, slide_context=full_context):
        return False

    obs_topics = extract_observation_topics(obs)
    if not obs_topics:
        return False

    financial_topics = {
        TOPIC_REVENUE, TOPIC_PROFITABILITY, TOPIC_OPEX,
        TOPIC_LIQUIDITY, TOPIC_DEBT, TOPIC_CASH_FLOW,
    }
    is_financial_obs = bool(obs_topics & financial_topics) or any(
        SUB_TO_PARENT.get(t) in financial_topics for t in obs_topics
    )

    # 2. Broad slide titles (e.g. "Historical Financial Performance Overview")
    title_topics = extract_topics_from_text(slide.title)
    if TOPIC_FINANCIAL_BROAD in title_topics and is_financial_obs:
        return False

    # 3. If this is a supporting KPI on a hybrid layout (e.g. chart_plus_kpis),
    # where the primary chart already presents the slide topic, supporting financial KPIs
    # (margins, profitability, growth, liquidity) in a financial section or alongside
    # financial charts are contextually valid and do not constitute a contradictory mismatch.
    if is_supporting_kpi and is_financial_obs:
        slide_section = (getattr(slide, "section_title", None) or "").casefold()
        is_financial_section = any(
            term in slide_section
            for term in ("financial", "performance", "results", "overview", "condition", "highlights")
        )
        context_topics = extract_topics_from_text(full_context)
        has_financial_context = any(
            t in financial_topics or SUB_TO_PARENT.get(t) in financial_topics
            for t in context_topics
        )
        if is_financial_section or has_financial_context:
            return False

    # 4. Extract specific topics for slide
    slide_topics = extract_topics_from_text(full_context)

    # If the slide declares NO specific exclusive financial topic (broad overview / operational summary),
    # absence of overlap is NOT positive evidence of mismatch
    if not slide_topics:
        return False

    # 5. Positive evidence: slide has a specific topic, and observation belongs to
    # a completely disjoint, incompatible parent group.
    slide_parent_groups = {SUB_TO_PARENT.get(t, t) for t in slide_topics}
    obs_parent_groups = {SUB_TO_PARENT.get(t, t) for t in obs_topics}

    if slide_parent_groups and obs_parent_groups and slide_parent_groups.isdisjoint(obs_parent_groups):
        return True

    # Slide has a specific sub-topic (e.g. R&D only) and obs is a different sub-topic (e.g. Gross Profit)
    # where direct text match and token overlap failed
    if not (slide_topics & obs_topics):
        # Verify that slide does NOT declare the parent umbrella (e.g. OpEx)
        has_umbrella = any(
            parent in slide_topics for parent in {TOPIC_OPEX, TOPIC_PROFITABILITY, TOPIC_LIQUIDITY}
        )
        if not has_umbrella:
            return True

    return False


def filter_observations_by_slide_topic(
    observations: list[Observation],
    slide_title: str,
    slide_context: str | None = None,
) -> list[Observation]:
    """Filter observations to those compatible with the slide topic."""
    if not observations or not slide_title:
        return observations

    full_context = f"{slide_title} {slide_context or ''}".strip()
    slide_topics = extract_topics_from_text(full_context)
    title_tokens = extract_topic_tokens(full_context)

    # If slide is broad with no exclusive topic, retain all observations
    if not slide_topics and not title_tokens:
        return observations

    matching: list[Observation] = []
    for obs in observations:
        if metrics_match_topic(obs, "", slide_title, slide_context=full_context):
            matching.append(obs)
    return matching
