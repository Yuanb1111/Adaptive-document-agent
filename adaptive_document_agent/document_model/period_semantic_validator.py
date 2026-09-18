"""Period semantic classification and point-in-time / interim date formatting."""

from __future__ import annotations

from dataclasses import dataclass
import re

MONTH_MAP = {
    "jan": 1, "january": 1, "一月": 1,
    "feb": 2, "february": 2, "二月": 2,
    "mar": 3, "march": 3, "三月": 3,
    "apr": 4, "april": 4, "四月": 4,
    "may": 5, "五月": 5,
    "jun": 6, "june": 6, "六月": 6,
    "jul": 7, "july": 7, "七月": 7,
    "aug": 8, "august": 8, "八月": 8,
    "sep": 9, "september": 9, "九月": 9,
    "oct": 10, "october": 10, "十月": 10,
    "nov": 11, "november": 11, "十一月": 11,
    "dec": 12, "december": 12, "十二月": 12,
}
MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


@dataclass(frozen=True)
class PeriodSemantic:
    period_type: str  # 'fiscal_year', 'interim_flow', 'balance_sheet_date', 'point_in_time', 'generic'
    clean_label: str
    is_unaudited: bool
    is_interim: bool
    as_of_date: str | None = None
    period_start: str | None = None
    period_end: str | None = None


def format_period_label(
    period: str | None,
    *,
    is_balance_sheet: bool = False,
    is_unaudited: bool = False,
) -> str:
    if not period:
        return ""
    p = " ".join(str(period).strip().split())

    num_word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
    }

    # 0. Interim month flow periods: e.g. "six months ended 30 Jun 2021" -> "6M2021"
    if not is_balance_sheet:
        if m := re.search(r"(?i)(?:for\s+the\s+)?(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d{1,2})\s*months?\s*ended\s+.*?\b(20\d{2})\b", p):
            count_str = m.group(1).casefold()
            count_num = num_word_map.get(count_str, int(count_str) if count_str.isdigit() else None)
            year_num = m.group(2)
            if count_num:
                star = "*" if (is_unaudited or "*" in p) else ""
                return f"{count_num}M{year_num}{star}"

        if m := re.search(r"(?:截至\s*)?(20\d{2})年.*?止\s*([一二三四五六七八九十0-9]{1,2})\s*个?月", p):
            year_num = m.group(1)
            count_str = m.group(2)
            count_num = num_word_map.get(count_str, int(count_str) if count_str.isdigit() else None)
            if count_num:
                star = "*" if (is_unaudited or "*" in p) else ""
                return f"{count_num}M{year_num}{star}"

    is_bs_point = is_balance_sheet or bool(re.search(r"(?i)\b(?:as\s+at|as\s+of|at)\b", p))

    # 1. ISO Date: YYYY-MM-DD
    if m := re.search(r"\b(20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", p):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mon_str = MONTH_ABBR.get(month, f"{month:02d}")
        star = "*" if (is_unaudited or (is_balance_sheet and month != 12) or "*" in p) else ""
        return f"{day} {mon_str} {year}{star}"

    # 2. Text Date: "30 April 2025" or "April 30, 2025" or "February 28, 2026"
    if m := re.search(r"(?i)\b([0-3]?\d)\s+([A-Za-z]+)\s+(20\d{2})\b", p):
        day = int(m.group(1))
        mon_key = m.group(2).casefold()
        year = int(m.group(3))
        if mon_key in MONTH_MAP:
            month = MONTH_MAP[mon_key]
            mon_str = MONTH_ABBR[month]
            star = "*" if (is_unaudited or (is_balance_sheet and month != 12) or "*" in p) else ""
            return f"{day} {mon_str} {year}{star}"

    if m := re.search(r"(?i)\b([A-Za-z]+)\s+([0-3]?\d)[,\s]+(20\d{2})\b", p):
        mon_key = m.group(1).casefold()
        day = int(m.group(2))
        year = int(m.group(3))
        if mon_key in MONTH_MAP:
            month = MONTH_MAP[mon_key]
            mon_str = MONTH_ABBR[month]
            star = "*" if (is_unaudited or (is_balance_sheet and month != 12) or "*" in p) else ""
            return f"{day} {mon_str} {year}{star}"

    # 3. CJK Date: "2025年4月30日" or "2026年2月28日"
    if m := re.search(r"(20\d{2})年([0-1]?\d)月([0-3]?\d)日?", p):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mon_str = MONTH_ABBR.get(month, f"{month:02d}")
        star = "*" if (is_unaudited or (is_balance_sheet and month != 12) or "*" in p) else ""
        return f"{day} {mon_str} {year}{star}"

    # 4. Interim month flow: 4M2024 / 4M2025 / 6M2025 / 9M2025
    if m := re.match(r"(?i)^([0-9]{1,2}M)\s*(?:20)?(\d{2})\*?$", p):
        prefix = m.group(1).upper()
        year_suffix = m.group(2)
        if is_balance_sheet:
            months = int(prefix[:-1])
            mon_str = MONTH_ABBR.get(months, "Interim")
            last_day = 30 if months in (4, 6, 9, 11) else (28 if months == 2 else 31)
            return f"{last_day} {mon_str} 20{year_suffix}*"
        return f"{prefix}20{year_suffix}"

    # 5. Explicit FY or year
    if m := re.match(r"(?i)^(?:FY\s*)?(20\d{2})$", p):
        year = m.group(1)
        star = "*" if (is_unaudited or "*" in p) else ""
        return f"FY{year}{star}"

    if is_unaudited and not p.endswith("*"):
        return f"{p}*"

    return p


def format_observation_period(
    obs: object,
    *,
    is_balance_sheet: bool | None = None,
) -> str:
    """Format a period label from an Observation, auto-detecting balance-sheet status.

    Priority order:
    1. Use obs.as_of_date (ISO date) if present — most precise.
    2. Derive is_balance_sheet from obs.period_type if not explicitly provided.
    3. Append '*' when obs.audited_status == 'unaudited' or period is interim.
    4. Fall back to format_period_label(obs.period, is_balance_sheet=...).
    """
    period: str | None = getattr(obs, "period", None)
    period_type: str = getattr(obs, "period_type", "generic") or "generic"
    as_of_date: str | None = getattr(obs, "as_of_date", None)
    audited_status: str = getattr(obs, "audited_status", "unknown") or "unknown"

    # Determine is_balance_sheet if not explicitly supplied
    if is_balance_sheet is None:
        is_balance_sheet = period_type in ("balance_sheet_date", "point_in_time")
        if not is_balance_sheet:
            metric_str = (
                f"{getattr(obs, 'metric_canonical', '') or ''} "
                f"{getattr(obs, 'metric_original', '') or ''}"
            ).casefold()
            bs_keywords = (
                "liabilit", "asset", "equity", "cash", "balance",
                "receiv", "payab", "inventor", "deficit", "borrowing",
                "working capital", "net current", "资产", "负债", "资本",
            )
            is_balance_sheet = any(k in metric_str for k in bs_keywords)

    is_unaudited = audited_status == "unaudited"

    # Use as_of_date (most precise source)
    if as_of_date:
        return format_period_label(as_of_date, is_balance_sheet=is_balance_sheet, is_unaudited=is_unaudited)

    return format_period_label(period, is_balance_sheet=is_balance_sheet, is_unaudited=is_unaudited)


def format_canonical_period(
    item: object,
    *,
    is_balance_sheet: bool | None = None,
    is_unaudited: bool = False,
) -> str:
    """Universal canonical period display function.

    Accepts an Observation object or a period string, returning the canonical formatted label.
    Point-in-time balance sheet dates return e.g. '30 Apr 2025*', never 'FY2025'.
    """
    if item is None:
        return ""
    if hasattr(item, "period") or hasattr(item, "period_type"):
        return format_observation_period(item, is_balance_sheet=is_balance_sheet)
    return format_period_label(str(item), is_balance_sheet=bool(is_balance_sheet), is_unaudited=is_unaudited)



def is_interim_date(period: str | None) -> bool:
    if not period:
        return False
    p = str(period).casefold()
    if any(k in p for k in ("interim", "unaudited", "*")):
        return True
    if re.search(r"\b[0-9]{1,2}m\b", p):
        return True
    # If it is a point-in-time date other than Dec 31
    if m := re.search(r"\b(20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", p):
        month = int(m.group(2))
        return month != 12
    for mon_name, month_num in MONTH_MAP.items():
        if mon_name in p and month_num != 12 and any(char.isdigit() for char in p):
            return True
    return False


def period_sort_key_extended(period: str | None) -> tuple[int, int, int, str]:
    if not period:
        return (9999, 99, 99, "")
    p = str(period).strip()
    year = 9999
    month = 12
    day = 31

    if m := re.search(r"\b(20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", p):
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        return (year, month, day, p)

    if m := re.search(r"(?:20)?(\d{2})", p):
        year = int(f"20{m.group(1)}")

    if m := re.search(r"\b([0-9]{1,2})m\b", p.casefold()):
        month = int(m.group(1))
        day = 30
        return (year, month, day, p)

    for mon_name, month_num in MONTH_MAP.items():
        if mon_name in p.casefold():
            month = month_num
            if d_match := re.search(r"\b([0-3]?\d)\b", p):
                val = int(d_match.group(1))
                if 1 <= val <= 31:
                    day = val
            break

    return (year, month, day, p)


def classify_period(period: str | None, *, is_balance_sheet: bool = False) -> PeriodSemantic:
    if not period:
        return PeriodSemantic(period_type="generic", clean_label="", is_unaudited=False, is_interim=False)

    p = str(period).strip()
    formatted = format_period_label(p, is_balance_sheet=is_balance_sheet)
    is_unaudited = "*" in formatted or "unaudited" in p.casefold()
    is_interim = is_unaudited or is_interim_date(p)

    # Detect exact point-in-time date
    as_of: str | None = None
    if m := re.search(r"\b(20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", p):
        as_of = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    elif m := re.search(r"(?i)\b([0-3]?\d)\s+([A-Za-z]+)\s+(20\d{2})\b", p):
        d, m_str, y = int(m.group(1)), m.group(2).casefold(), int(m.group(3))
        if m_str in MONTH_MAP:
            as_of = f"{y}-{MONTH_MAP[m_str]:02d}-{d:02d}"
    elif m := re.search(r"(?i)\b([A-Za-z]+)\s+([0-3]?\d)[,\s]+(20\d{2})\b", p):
        m_str, d, y = m.group(1).casefold(), int(m.group(2)), int(m.group(3))
        if m_str in MONTH_MAP:
            as_of = f"{y}-{MONTH_MAP[m_str]:02d}-{d:02d}"
    elif m := re.search(r"(20\d{2})年([0-1]?\d)月([0-3]?\d)日?", p):
        as_of = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # A date inside an interim flow label is the period end, not a point-in-time
    # balance-sheet observation.  Classify the duration before considering the
    # embedded date.
    formatted_basis = extract_period_basis(formatted)
    if formatted_basis not in {"generic", "FY", "point_in_time"} and not is_balance_sheet:
        ptype = "interim_flow"
        as_of = None
    elif as_of:
        ptype = "balance_sheet_date" if is_balance_sheet else "point_in_time"
    elif is_balance_sheet and (is_interim or any(mon in formatted.casefold() for mon in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov"))):
        ptype = "balance_sheet_date"
    elif re.search(r"(?i)\b(?:Q[1-4]|1Q|2Q|3Q|4Q)\s*(?:20)?\d{2}\b", p):
        ptype = "quarter"
    elif re.search(r"(?i)\b(?:1H|2H|H1|H2)\s*(?:20)?\d{2}\b", p):
        ptype = "interim_period"
    elif re.search(r"(?i)\bYTD\b", p):
        ptype = "ytd"
    elif re.match(r"(?i)^[0-9]{1,2}m", formatted) or (is_interim and re.match(r"(?i)^[0-9]{1,2}m", p)):
        ptype = "interim_flow"
    elif is_interim:
        ptype = "interim_flow"
    elif re.match(r"(?i)^(?:FY\s*)?(?:19|20)\d{2}$", p):
        ptype = "fiscal_year"
    else:
        ptype = "generic"

    return PeriodSemantic(
        period_type=ptype,
        clean_label=formatted,
        is_unaudited=is_unaudited,
        is_interim=is_interim,
        as_of_date=as_of or (formatted if ptype in {"balance_sheet_date", "point_in_time"} else None),
    )


def extract_period_basis(period: str | None) -> str:
    """Extract standard period basis duration/type ('FY', '6M', '3M', '4M', '9M', 'point_in_time', 'generic')."""
    if not period:
        return "generic"
    p = str(period).strip()
    if m := re.search(r"(?i)\b([0-9]{1,2})M(?:\d{2,4})?\b", p):
        return f"{m.group(1)}M".upper()
    if re.search(r"(?i)\b(?:1H|2H|H1|H2)\b", p):
        return "6M"
    if re.search(r"(?i)\b(?:Q[1-4]|[1-4]Q)\b", p):
        return "3M"
    if re.search(r"(?i)six\s*months?\s*ended", p) or "六个月" in p:
        return "6M"
    if re.search(r"(?i)three\s*months?\s*ended", p) or "三个月" in p:
        return "3M"
    if re.search(r"(?i)four\s*months?\s*ended", p) or "四个月" in p:
        return "4M"
    if re.search(r"(?i)nine\s*months?\s*ended", p) or "九个月" in p:
        return "9M"
    if re.search(r"(?i)\b(?:as\s+at|as\s+of)\b", p) or re.search(r"\b\d{1,2}\s+[A-Za-z]{3,}\s+\d{4}\b", p):
        return "point_in_time"
    if re.search(r"(?i)year\s*ended|^\s*(?:FY\s*)?(?:19|20)\d{2}\*?\s*$", p):
        return "FY"
    return "generic"


def are_periods_comparable(p1: str | None, p2: str | None) -> tuple[bool, str]:
    """Check if two periods are comparable for trends/movements (e.g. FY vs FY, 6M vs 6M)."""
    b1 = extract_period_basis(p1)
    b2 = extract_period_basis(p2)
    if b1 == "generic" or b2 == "generic":
        return True, ""
    if b1 != b2:
        return False, f"Incompatible period basis: '{b1}' ({p1}) vs '{b2}' ({p2})"
    return True, ""

