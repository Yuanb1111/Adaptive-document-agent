"""Resolve centered period superheaders from PDF coordinates, never metric names."""

import re
from itertools import combinations

from .borderless_layout import SourceLine

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_MONTHS = {name: i for i, name in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)}


def geometric_periods(headers: list[SourceLine], year_line: SourceLine, width: int) -> list[str] | None:
    """Assign contiguous year groups only when their centers match source headings.

    A heading centered over three years applies to that group, not merely the
    nearest year. Split-line interim headings are resolved by their duration
    phrase. Ambiguous, missing or prose-only geometry leaves periods unresolved.
    """
    matches = list(_YEAR.finditer(year_line.text))
    boxes = [year_line.bounds(m.start(), m.end()) for m in matches]
    if not boxes or len(boxes) > 24 or not all(boxes) or width % len(boxes):
        return None
    centers = [(a + b) / 2 for a, b in boxes]
    gap = min((b - a for a, b in zip(centers, centers[1:])), default=0)
    if gap <= 0:
        return None
    # Nearby short header tiers only: do not interpret dates in preceding prose.
    tiers = []
    for line in reversed(headers):
        if len(line.text) > 95 or line.text.endswith(".") or _YEAR.search(line.text):
            break
        tiers.insert(0, line)
    context = " ".join(line.text for line in tiers).casefold()
    snapshot = bool(re.search(r"\bas\s+(?:of|at)\b", context)) and not re.search(r"year\s+ended|months?\s+ended", context)
    descriptors = []
    duration = re.compile(r"\b(year\s+ended|(three|six|nine|twelve|3|6|9|12)\s+months?)\b", re.I)
    date = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\b", re.I)
    for line in tiers:
        for match in (date if snapshot else duration).finditer(line.text):
            bounds = line.bounds(match.start(), match.end())
            if not bounds:
                return None
            # The whole phrase is centered, not just 'December 31' in 'As of ...'.
            start, end = match.span()
            nearby = [s for s in line.spans if s[0] < end and s[1] > start]
            if nearby:
                first = line.spans.index(nearby[0])
                last = line.spans.index(nearby[-1])
                while first > 0 and line.spans[first][2] - line.spans[first-1][3] < min(12, gap*.2):
                    first -= 1
                while last + 1 < len(line.spans) and line.spans[last+1][2] - line.spans[last][3] < min(12, gap*.2):
                    last += 1
                bounds = line.spans[first][2], line.spans[last][3]
            if snapshot:
                month, day = _MONTHS[match.group(1).casefold()], int(match.group(2))
                if not 1 <= day <= 31:
                    return None
                label = f"-{month:02d}-{day:02d}"
            else:
                token = (match.group(2) or "").casefold()
                label = "FY" if not token else f"{ {'three': 3, 'six': 6, 'nine': 9, 'twelve': 12}.get(token, token)}M"
            item = ((bounds[0] + bounds[1]) / 2, label)
            if item not in descriptors:
                descriptors.append(item)
    descriptors.sort()
    count = len(descriptors)
    if not count or count > min(len(centers), 4):
        return None
    fits = []
    for breaks in combinations(range(1, len(centers)), count - 1):
        edges = (0, *breaks, len(centers))
        errors = [abs(sum(centers[a:b]) / (b-a) - x) / gap
                  for (a, b), (x, _) in zip(zip(edges, edges[1:]), descriptors)]
        if max(errors) <= .6:
            fits.append((sum(e*e for e in errors), edges))
    fits.sort()
    if not fits or (len(fits) > 1 and fits[1][0] - fits[0][0] < .08):
        return None
    labels = []
    for (a, b), (_, label) in zip(zip(fits[0][1], fits[0][1][1:]), descriptors):
        for match in matches[a:b]:
            value = match.group() + label if snapshot else label + match.group()
            labels.extend([value] * (width // len(matches)))
    return labels
