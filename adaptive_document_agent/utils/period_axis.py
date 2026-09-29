"""Pure checks for chart period cadence shared by planning and rendering."""

import re


def has_complete_period_cadence(categories: list[str]) -> bool:
    """Return whether annual or quarterly labels form a gap-free sequence.

    Unknown and point-in-time labels fail closed because filled area would
    imply values for periods the source did not report.
    """
    if len(categories) < 3:
        return False
    annual = [re.fullmatch(r"(?:FY|CY)?\s*((?:19|20)\d{2})\*?", label.strip(), re.I)
              for label in categories]
    if all(annual):
        years = [int(match.group(1)) for match in annual]
        return all(right - left == 1 for left, right in zip(years, years[1:]))
    quarterly = [re.fullmatch(r"(?:Q([1-4])\s*((?:19|20)\d{2})|((?:19|20)\d{2})\s*Q([1-4]))\*?", label.strip(), re.I)
                 for label in categories]
    if all(quarterly):
        positions = [int(match.group(2) or match.group(3)) * 4 + int(match.group(1) or match.group(4))
                     for match in quarterly]
        return all(right - left == 1 for left, right in zip(positions, positions[1:]))
    return False
