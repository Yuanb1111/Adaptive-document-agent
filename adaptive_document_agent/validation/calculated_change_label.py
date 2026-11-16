"""Bind explicitly labelled cumulative changes to exact Python calculations."""
import re
from adaptive_document_agent.services.calendar_claims import period_identity

_LABEL = re.compile(r'\b(?:calculated|computed|recalculated|recomputed)\s+'
    r'(?:(?:cumulative|percentage|percent|total)\s+)*(?P<kind>increase|decrease|change|growth)'
    r'(?:\s+(?:in|of)\s+(?P<metric>[^;.!?]+?))?\s*(?:(?:was|were|is|equals?)\s*|:\s*)$', re.I)
_METRIC_FIRST_LABEL = re.compile(r'\b(?:calculated|computed|recalculated|recomputed)\s+'
    r'(?P<metric>[^;.!?]+?)\s+(?:(?:cumulative|percentage|percent|total)\s+)*'
    r'(?P<kind>increase|decrease|change|growth)\s*(?:(?:was|were|is|equals?)\s*|:\s*)$',re.I)
_PERIOD=r'(?:FY|[1-9]M|1[0-2]M|Q[1-4]|[12]H)?(?:19|20)\d{2}(?:-\d{2}-\d{2})?E?'
_INTERVAL = re.compile(rf'\b({_PERIOD})\s*(?:[-–—]|\bto\b)\s*(?:as\s+of\s+)?({_PERIOD})\b', re.I)


def labelled_change_supported(clause, prefix, literal, calculations):
    """A level, wrong interval, CAGR or wrong signed direction cannot borrow it."""
    label = _LABEL.search(prefix)
    metric_first = label is None
    if metric_first:label = _METRIC_FIRST_LABEL.search(prefix)
    intervals = _INTERVAL.findall(clause)
    rate_context=clause
    if label and label['metric']:
        rate_context=clause[:label.start('metric')]+clause[label.end('metric'):]
    if not label or len(intervals) != 1 or re.search(r'\b(?:annual|annualized|CAGRs?)\b', rate_context, re.I):
        return False
    ends = [period_identity(p) for p in intervals[0]]
    eligible = [c for c in calculations if c['kind'] in {'percentage_change', 'yoy_percentage_change'}
                and c['unit'] == 'percent' and [period_identity(c['periods'][0]), period_identity(c['periods'][-1])] == ends]
    scope = label['metric']
    if scope:
        if metric_first:
            from .presentation_metric_binding import source_label_forms
            normalize=lambda value:' '.join(value.casefold().split())
            eligible=[c for c in eligible if normalize(scope) in
                      {normalize(form) for form in source_label_forms(c['metric'])}]
        else:
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
