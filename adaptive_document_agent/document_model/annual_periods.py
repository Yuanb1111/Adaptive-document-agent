"""Resolve explicit annual labels without assuming missing reporting periods."""

import re

from .period_semantic_validator import classify_period, extract_period_basis


def annual_period_year(period: str | None) -> int:
    """Return a unique four-digit year only for an explicitly annual period."""
    label = re.sub(r"\s*\((?:un)?audited\)\s*", "", period or "", flags=re.IGNORECASE).strip().rstrip("*").strip()
    years = set(re.findall(r"\b(?:19|20)\d{2}\b|(?<=FY)(?:19|20)\d{2}\b", label, flags=re.IGNORECASE))
    explicitly_annual = extract_period_basis(label) == "FY" or bool(re.search(r"\byear\s+ended\b", label, re.IGNORECASE))
    if not explicitly_annual or len(years) != 1:
        raise ValueError("CAGR requires explicit annual periods with an unambiguous four-digit year.")
    return int(next(iter(years)))


def annual_span(periods: list[str | None]) -> int:
    """Use elapsed years, not the number of available observations."""
    years = [annual_period_year(period) for period in periods]
    if len(years) < 2 or len(set(years)) != len(years):
        raise ValueError("CAGR requires at least two distinct annual periods without duplicate years.")
    disclosed_ends = [classify_period(period).as_of_date for period in periods]
    anniversaries = {end[5:] for end in disclosed_ends if end and re.fullmatch(r"\d{4}-\d{2}-\d{2}", end)}
    if len(anniversaries) > 1:
        raise ValueError("CAGR cannot assume whole years when disclosed reporting year-end dates differ.")
    return max(years) - min(years)
