"""Bind explicitly labelled cumulative changes to exact Python calculations."""
import re

_LABEL = re.compile(r'\b(?:calculated|computed|recalculated|recomputed)\s+'
    r'(?:(?:cumulative|percentage|percent|total)\s+)*(?P<kind>increase|decrease|change|growth)'
    r'(?:\s+(?:in|of)\s+(?P<metric>[^;.!?]+?))?\s+(?:was|were|is|equals?)\s*$', re.I)
_INTERVAL = re.compile(r'\b((?:FY)?(?:19|20)\d{2}E?)\s*(?:[-–—]|\bto\b)\s*'
                       r'((?:FY)?(?:19|20)\d{2}E?)\b', re.I)


def labelled_change_supported(clause, prefix, literal, calculations):
    """A level, wrong interval, CAGR or wrong signed direction cannot borrow it."""
    label = _LABEL.search(prefix)
    intervals = _INTERVAL.findall(clause)
    if not label or len(intervals) != 1 or re.search(r'\b(?:annual|annualized|CAGR)\b', clause, re.I):
        return False
    ends = [p.upper() for p in intervals[0]]
    eligible = [c for c in calculations if c['kind'] in {'percentage_change', 'yoy_percentage_change'}
                and c['unit'] == 'percent' and [c['periods'][0].upper(), c['periods'][-1].upper()] == ends]
    scope = label['metric']
    if scope:
        eligible = [c for c in eligible if c['metric'].casefold() in scope.casefold()]
    elif len({c['metric'] for c in eligible}) != 1:
        return False
    claimed = float(literal)
    places = len(literal.split('.', 1)[1]) if '.' in literal else 0
    for calculation in eligible:
        value = calculation['value']
        kind = label['kind'].casefold()
        if kind in {'increase', 'growth', 'decrease'}:
            if claimed < 0 or (kind == 'decrease' and value >= 0) or (kind != 'decrease' and value <= 0):
                continue
            value = abs(value)
        if round(value, places) == claimed:
            return True
    return False
