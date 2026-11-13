"""Resolve a written date enumeration without borrowing endpoints from data."""
import re

_YEAR = r'(?:19|20)\d{2}'
_PERIOD = rf'(?:{_YEAR}-\d{{2}}-\d{{2}}|(?:FY\s*|[1369]M\s*|[12]H\s*|Q[1-4]\s*)?{_YEAR})'
_MENTION = re.compile(rf'\b{_PERIOD}\b', re.I)
_LIST = re.compile(rf'\b(?:as\s+of|at|in)\s+(?P<dates>{_PERIOD}'
                   rf'(?:\s*,\s*{_PERIOD})+(?:\s*,?\s*and\s+{_PERIOD}))\b', re.I)


def explicit_period_list(text):
    """Return one complete enumeration only when it owns every stated period."""
    matches = list(_LIST.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    mentions = list(_MENTION.finditer(text))
    if not all(match.start('dates') <= m.start() < m.end() <= match.end('dates') for m in mentions):
        return None
    return match[0], [m[0] for m in mentions]


def enumerated_segments(text, observations):
    """Bind all adjacent listed dates; reject gaps, duplicates and changed bases."""
    explicit = explicit_period_list(text)
    if explicit is None:
        return None
    normalize = lambda value: re.sub(r'\s+', '', value or '').casefold()
    indices = []
    for period in explicit[1]:
        matches = [i for i, item in enumerate(observations) if normalize(item.period) == normalize(period)]
        if len(matches) != 1:
            return []
        indices.append(matches[0])
    if any(last != first + 1 for first, last in zip(indices, indices[1:])):
        return []
    return [observations[first:last + 1] for first, last in zip(indices, indices[1:])]
