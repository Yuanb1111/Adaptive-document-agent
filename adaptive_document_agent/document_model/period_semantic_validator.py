"""Period semantic classification and interim date formatting."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PeriodSemantic:
    period_type: str  # 'fiscal_year', 'interim_flow', 'balance_sheet_date', 'generic'
    clean_label: str
    is_unaudited: bool
    is_interim: bool


def format_period_label(
    period: str | None,
    *,
    is_balance_sheet: bool = False,
    is_unaudited: bool = False,
) -> str:
    if not period:
        return ""
    p = " ".join(str(period).strip().split())

    # April 30, 2025 / 30 Apr 2025 / 2025-04-30
    if re.search(r"(?i)(?:30\s*apr(?:il)?|april\s*30)[,\s]*(?:20)?(\d{2})", p) or re.search(r"(?i)20(\d{2})-04-30", p):
        m = re.search(r"(?i)(?:30\s*apr(?:il)?|april\s*30)[,\s]*(?:20)?(\d{2})", p) or re.search(r"(?i)20(\d{2})-04-30", p)
        year = m.group(1)
        return f"30 Apr 20{year}*"

    # 4M2024 / 4M2025
    if m := re.match(r"(?i)^4M\s*(?:20)?(\d{2})\*?$", p):
        year = m.group(1)
        if is_balance_sheet:
            return f"30 Apr 20{year}*"
        return f"4M20{year}"

    # Interim month abbreviations like 4M25, 6M25
    if m := re.match(r"(?i)^([0-9]{1,2}M)\s*(?:20)?(\d{2})\*?$", p):
        return f"{m.group(1).upper()}20{m.group(2)}"

    # Explicit FY
    if m := re.match(r"(?i)^(?:FY\s*)?(20\d{2})$", p):
        year = m.group(1)
        if is_balance_sheet and is_unaudited:
            return f"30 Apr {year}*"
        return f"FY{year}"

    if is_unaudited and not p.endswith("*"):
        return f"{p}*"

    return p


def is_interim_date(period: str | None) -> bool:
    if not period:
        return False
    p = str(period).casefold()
    return any(k in p for k in ("-04-30", "-06-30", "-09-30", "apr", "jun", "sep", "4m", "6m", "9m", "interim"))


def period_sort_key_extended(period: str | None) -> tuple[int, int, str]:
    if not period:
        return (9999, 99, "")
    p = str(period).strip()
    year_match = re.search(r"(?:20)?(\d{2})", p)
    year = int(f"20{year_match.group(1)}") if year_match else 9999
    # Prioritize FY before interim of same year, or according to month
    month = 12
    if "4m" in p.casefold() or "apr" in p.casefold():
        month = 4
    elif "6m" in p.casefold() or "jun" in p.casefold():
        month = 6
    elif "9m" in p.casefold() or "sep" in p.casefold():
        month = 9
    return (year, month, p)


def classify_period(period: str | None, *, is_balance_sheet: bool = False) -> PeriodSemantic:
    if not period:
        return PeriodSemantic(period_type="generic", clean_label="", is_unaudited=False, is_interim=False)

    p = str(period).strip()
    formatted = format_period_label(p, is_balance_sheet=is_balance_sheet)
    is_unaudited = "*" in formatted or "unaudited" in p.casefold()
    is_interim = is_unaudited or is_interim_date(p)

    ptype = "fiscal_year"
    if "apr" in formatted.casefold() or (is_balance_sheet and is_interim):
        ptype = "balance_sheet_date"
    elif is_interim:
        ptype = "interim_flow"

    return PeriodSemantic(
        period_type=ptype,
        clean_label=formatted,
        is_unaudited=is_unaudited,
        is_interim=is_interim,
    )
