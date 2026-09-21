"""Language QA and presentation text sanitization service.

Preserves exact raw evidence text while ensuring all presentation strings
(slide titles, KPI cards, table headers, narratives) are publication-grade.
"""

from __future__ import annotations

import re


# Common OCR misspellings and scanning artifacts in financial filings
_OCR_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bfulfient\b"), "fulfillment"),
    (re.compile(r"(?i)\bfulfilment\b"), "fulfillment"),
    (re.compile(r"(?i)\bfulfiling\b"), "fulfilling"),
    (re.compile(r"(?i)\bliabilties\b"), "liabilities"),
    (re.compile(r"(?i)\bliabilty\b"), "liability"),
    (re.compile(r"(?i)\breceviables?\b"), "receivables"),
    (re.compile(r"(?i)\brecevables?\b"), "receivables"),
    (re.compile(r"(?i)\bdepreciaton\b"), "depreciation"),
    (re.compile(r"(?i)\bamoritization\b"), "amortization"),
    (re.compile(r"(?i)\bamortisaton\b"), "amortization"),
    (re.compile(r"(?i)\badminstrative\b"), "administrative"),
    (re.compile(r"(?i)\badminstration\b"), "administration"),
    (re.compile(r"(?i)\bfianncial\b"), "financial"),
    (re.compile(r"(?i)\bfiannce\b"), "finance"),
    (re.compile(r"(?i)\bequitiy\b"), "equity"),
    (re.compile(r"(?i)\bunaduited\b"), "unaudited"),
    (re.compile(r"(?i)\bunaudtied\b"), "unaudited"),
    (re.compile(r"(?i)\brevneue\b"), "revenue"),
    (re.compile(r"(?i)\brevenu\b"), "revenue"),
    (re.compile(r"(?i)\bexpneses?\b"), "expenses"),
    (re.compile(r"(?i)\bexpnese\b"), "expense"),
    (re.compile(r"(?i)\boprton\b"), "operation"),
    (re.compile(r"(?i)\boprations?\b"), "operations"),
    (re.compile(r"(?i)\bmargn\b"), "margin"),
    (re.compile(r"(?i)\bdivdend\b"), "dividend"),
    (re.compile(r"(?i)\bcomprehensive\s+incom\b"), "comprehensive income"),
)

# Unedited internal pipeline prompt leaks
_PROMPT_LEAKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)calculated\s+change\s+result\s*:\s*"), "Analysis indicates "),
    (re.compile(r"(?i)calculated\s+change\s+result"), "Analysis indicates"),
    (re.compile(r"(?i)calculated\s+result\s*:\s*"), "Analysis indicates "),
    (re.compile(r"(?i)calculated\s+result"), "analysis indicates"),
    (re.compile(r"(?i)based\s+on\s+extracted\s+observations\b"), "Based on reported disclosures"),
    (re.compile(r"(?i)\bextracted\s+observations\b"), "reported disclosures"),
    (re.compile(r"(?i)\bretained\s+facts?\b"), "reported data"),
    (re.compile(r"(?i)\bretained\s+evidence\b"), "source disclosures"),
    (re.compile(r"(?i)\bdeterministic\s+analysis\s+produced\s*:\s*"), "Reported analysis indicates "),
    (re.compile(r"(?i)as\s+an\s+ai\s+language\s+model,?\s*"), ""),
    (re.compile(r"(?i)here\s+is\s+the\s+analysis\s*:\s*"), ""),
)


def _case_preserving_replace(pattern: re.Pattern[str], replacement: str, text: str) -> str:
    """Replace pattern with replacement while preserving title/upper case of match."""
    def _sub(match: re.Match[str]) -> str:
        matched_str = match.group(0)
        if matched_str.isupper():
            return replacement.upper()
        if matched_str[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement

    return pattern.sub(_sub, text)


def clean_presentation_text(text: str) -> str:
    """Clean narrative presentation text for slides and reports.

    Fixes OCR artifacts, removes internal prompt leaks, corrects double
    negatives, and removes mechanical trailing ellipses.
    Does NOT alter raw evidence or underlying numerical facts.
    """
    if not text:
        return ""

    clean = " ".join(text.strip().split())

    # Fix prompt leaks
    for pattern, replacement in _PROMPT_LEAKS:
        clean = pattern.sub(replacement, clean)

    # Fix OCR misspellings (case preserving)
    for pattern, replacement in _OCR_FIXES:
        clean = _case_preserving_replace(pattern, replacement, clean)

    # Fix double-negative phrasings (specific compound phrases first)
    clean = re.sub(r"(?i)\bnet\s+loss\s+widened\s+by\s+-([0-9.]+)", r"net loss narrowed by \1", clean)
    clean = re.sub(r"(?i)\bnet\s+profit\s+was\s+-([0-9.]+)%?", r"net loss was \1", clean)
    clean = re.sub(r"(?i)\bincreased\s+by\s+-([0-9.]+)", r"decreased by \1", clean)
    clean = re.sub(r"(?i)\bgrew\s+by\s+-([0-9.]+)", r"contracted by \1", clean)
    clean = re.sub(r"(?i)\bdeclined\s+by\s+-([0-9.]+)", r"increased by \1", clean)
    clean = re.sub(r"(?i)\bwidened\s+by\s+-([0-9.]+)", r"narrowed by \1", clean)
    clean = re.sub(r"(?i)\bnarrowed\s+by\s+-([0-9.]+)", r"widened by \1", clean)

    # Fix accidental duplicate words (e.g., 'the the', 'in in')
    clean = re.sub(r"\b([A-Za-z]+)\s+\1\b", r"\1", clean, flags=re.IGNORECASE)

    # Remove mechanical trailing ellipsis
    clean = re.sub(r"(?:\.{2,}|\u2026)+$", "", clean).strip()

    # Clean up irregular punctuation spacing and identical repeated punctuation (e.g., '..', ',,')
    clean = re.sub(r"\s+([,.:;?!])", r"\1", clean)
    clean = re.sub(r"([,.?:;!])\1+", r"\1", clean)

    return clean.strip()


def clean_metric_label(name: str, max_length: int | None = None) -> str:
    """Format and shorten financial metric labels for presentation slides.

    Transforms long database strings like:
    'Research and development expenses: share of revenue' -> 'R&D / Revenue'
    'Selling and distribution expenses: share of revenue' -> 'Selling & Distribution / Revenue'
    'Administrative expenses: share of revenue' -> 'Admin / Revenue'
    'Cost of sales: share of revenue' -> 'Cost of Sales / Revenue'

    Strictly avoids mechanical ellipsis ('...') when gracefully shortening.
    """
    if not name:
        return "Reported Metric"

    clean = " ".join(name.strip().split())

    # Remove extraneous punctuation and trailing ellipsis
    clean = re.sub(r"(?:\.{2,}|\u2026)+$", "", clean).strip()
    clean = re.sub(r"^[:\-\s]+|[:\-\s]+$", "", clean).strip()

    # Remove nonsensical unit suffixes embedded in labels
    clean = re.sub(r"(?i)\s*%\s*of\s*(?:rmb|usd|cny|hkd|eur)\b", "", clean).strip()

    # 1. Standard Expense Ratio mappings (R&D, S&M, Admin, Cost of Sales, SG&A)
    # Check R&D ratio
    if re.search(
        r"(?i)research\s+(?:and|&)\s+development(?:\s+expenses?)?\s*(?::\s*(?:share|as\s*%?|ratio)\s+(?:of\s+)?(?:total\s+)?revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio|\s*\(.*?(?:share|%|ratio).*?revenue.*?\))",
        clean,
    ) or (re.search(r"(?i)research\s+(?:and|&)\s+development", clean) and any(k in clean.casefold() for k in ("share of revenue", "% of revenue", "/ revenue"))):
        return "R&D / Revenue"

    # Check Selling & Marketing vs Selling & Distribution ratio
    is_sm_ratio = bool(
        re.search(
            r"(?i)(?:selling\s+(?:and|&)\s+(?:distribution|marketing)|sales\s+(?:and|&)\s+marketing)(?:\s+expenses?)?\s*(?::\s*(?:share|as\s*%?|ratio)\s+(?:of\s+)?(?:total\s+)?revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio|\s*\(.*?(?:share|%|ratio).*?revenue.*?\))",
            clean,
        )
        or (
            re.search(r"(?i)(?:selling|sales)\s+(?:and|&)\s+(?:distribution|marketing)", clean)
            and any(k in clean.casefold() for k in ("share of revenue", "% of revenue", "/ revenue"))
        )
    )
    if is_sm_ratio:
        if "marketing" in clean.casefold():
            return "Selling & Marketing / Revenue"
        return "Selling & Distribution / Revenue"

    # Check SG&A ratio
    if re.search(
        r"(?i)(?:sg&a|selling,?\s+(?:general\s+)?(?:and|&)\s+administrative)(?:\s+expenses?)?\s*(?::\s*(?:share|as\s*%?|ratio)\s+(?:of\s+)?(?:total\s+)?revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio)",
        clean,
    ):
        return "SG&A / Revenue"

    # Check Administrative expenses ratio
    if re.search(
        r"(?i)administrative\s+expenses?\s*(?::\s*(?:share|as\s*%?|ratio)\s+(?:of\s+)?(?:total\s+)?revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio|\s*\(.*?(?:share|%|ratio).*?revenue.*?\))",
        clean,
    ) or ("administrative" in clean.casefold() and any(k in clean.casefold() for k in ("share of revenue", "% of revenue", "/ revenue"))):
        return "Admin / Revenue"


    # Check Cost of Sales / Revenue ratio
    if re.search(
        r"(?i)cost\s+of\s+(?:sales|revenue|goods\s+sold)\s*(?::\s*(?:share|as\s*%?|ratio)\s+(?:of\s+)?(?:total\s+)?revenue|\s*as\s*%\s*of\s*revenue|\s*/\s*revenue|\s*ratio|\s*\(.*?(?:share|%|ratio).*?revenue.*?\))",
        clean,
    ) or ("cost of sales" in clean.casefold() and any(k in clean.casefold() for k in ("share of revenue", "% of revenue", "/ revenue"))):
        return "Cost of Sales / Revenue"

    # Check fulfillment ratio
    if re.search(r"(?i)warehouse\s+fulfillment(?:\s+solutions)?(?:\s+expenses?)?\s*(?::\s*share\s+of\s+revenue|/ revenue)", clean):
        return "Warehouse Fulfillment / Revenue"

    # 2. Standard Financial Item mappings (nominal / currency)
    if re.fullmatch(r"(?i)research\s+(?:and|&)\s+development(?:\s+expenses?)?", clean):
        return "R&D Expenses"
    if re.fullmatch(r"(?i)(?:selling\s+(?:and|&)\s+distribution|selling\s+(?:and|&)\s+marketing)(?:\s+expenses?)?", clean):
        return "Selling & Marketing" if "marketing" in clean.casefold() else "Selling & Distribution"
    if re.fullmatch(r"(?i)administrative\s+expenses?", clean):
        return "Admin Expenses"
    if re.fullmatch(r"(?i)(?:sg&a|selling,?\s+general\s+(?:and|&)\s+administrative\s+expenses?)", clean):
        return "SG&A Expenses"
    if re.fullmatch(r"(?i)cost\s+of\s+(?:sales|revenue|goods\s+sold)", clean):
        return "Cost of Sales"
    if re.search(r"(?i)\bcash\s+and\s+cash\s+equivalents\b", clean):
        return "Cash & Cash Equivalents"
    if re.search(r"(?i)\btrade\s+and\s+(?:bills\s+)?receivables\b", clean):
        return "Trade Receivables"
    if re.search(r"(?i)\btrade\s+and\s+(?:bills\s+)?payables\b", clean):
        return "Trade Payables"
    if re.search(r"(?i)\bproperty,\s+plant\s+and\s+equipment\b", clean):
        return "PP&E"
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

    # Remove verbose prefixes and suffixes
    clean = re.sub(r"(?i)^the\s+group'?s?\s+", "", clean)
    clean = re.sub(r"(?i)\s+for\s+the\s+year$", "", clean)
    clean = re.sub(r"(?i)\s+for\s+the\s+period$", "", clean)
    clean = re.sub(r"(?i)\s+attributable\s+to\s+owners\s+of\s+the\s+parent$", "", clean)
    clean = re.sub(r"(?i)\s*%\s*of\s*(?:total\s+)?revenue$", " / Revenue", clean)

    # If max_length is specified, truncate gracefully at word boundary WITHOUT ellipses
    if max_length and len(clean) > max_length:
        clipped = clean[:max_length].rsplit(" ", 1)[0].rstrip(" ,:;-")
        clean = clipped if clipped else clean[:max_length]

    # Ensure no trailing ellipsis remained
    clean = re.sub(r"(?:\.{2,}|\u2026)+$", "", clean).strip()

    return clean


def polish_slide_title(title: str) -> str:
    """Polish presentation slide titles to maintain institutional quality.

    Avoids awkward machine-assembled titles such as:
    'Net Widened From FY2020 to FY2022 and Trajectory' -> 'Net Loss Widened Across FY2020–FY2022'
    'R&D Expenses Held Broadly Flat Before Rising in Trajectory' -> 'R&D Expenses Held Broadly Flat Before Rising'
    'Selling and Marketing Expenses Rose, With Trajectory' -> 'Selling and Marketing Expenses Rose'
    'Robot Lawn Mowers Became a Material Revenue Trajectory' -> 'Robot Lawn Mowers Became a Material Revenue Driver'
    """
    if not title:
        return ""
    t = " ".join(title.strip().split())

    # Replace awkward noun substitutions like "Material Revenue Trajectory" -> "Material Revenue Driver"
    t = re.sub(r"(?i)\bmaterial\s+revenue\s+trajectory\b", "Material Revenue Driver", t)

    # Remove redundant prepositions before Trajectory (e.g. ', With Trajectory', ' in Trajectory', ' and Trajectory')
    t = re.sub(r"(?i)[,\s]+(?:with|in|of|and)\s+trajectory\b", "", t).strip()
    t = re.sub(r"(?i)\s+and\s+trajectory\b", "", t).strip()

    trend_verbs = (
        "widened", "narrowed", "increased", "decreased", "grew", "contracted",
        "turned", "swung", "rose", "fell", "held", "became", "expanded",
        "surged", "dropped", "declined", "rebounded", "recovered", "rising", "falling",
    )

    # Replace mechanical suffix "Trajectory" -> "Overview" (e.g. "Revenue Trajectory" -> "Revenue Overview")
    if not any(w in t.casefold() for w in trend_verbs):
        if re.search(r"(?i)\btrajectory$", t):
            t = re.sub(r"(?i)\btrajectory$", "Overview", t).strip()
    else:
        t = re.sub(r"(?i)\s+trajectory\b", "", t).strip()

    # Strip any dangling prepositions/conjunctions left at the end of the title
    t = re.sub(r"(?i)[,\s]+(?:with|in|of|and|as|at|before|from|to)$", "", t).strip(" ,:;-")

    # Expand solitary 'Net' before trend verb to 'Net Loss' or 'Net Profit'
    t = re.sub(r"(?i)^Net\s+(widened|narrowed)\b", r"Net Loss \1", t)
    t = re.sub(r"(?i)^Net\s+(increased|decreased|grew|rose)\b", r"Net Profit \1", t)

    # Clean awkward 'From ... to ...' phrasing into professional range
    t = re.sub(r"(?i)\bfrom\s+(FY\d{4}|20\d{2})\s+to\s+(FY\d{4}|20\d{2})\b", r"Across \1–\2", t)

    # Limit to natural titles under 15 words
    words = t.split()
    if len(words) > 15:
        t = " ".join(words[:14]).strip(" ,:;-")
        t = re.sub(r"(?i)[,\s]+(?:with|in|of|and|as|at|before|from|to)$", "", t).strip(" ,:;-")

    return t
