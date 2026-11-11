"""Recognize a source-attributed nominal shape, never a numeric predicate."""
import re

from adaptive_document_agent.services.calendar_claims import bound_period_dates

_NOUN = (r'(?:(?:initial|subsequent|later|early|temporary|sharp|modest|reported|brief)\s+)*'
         r'(?:dip|decline|decrease|fall|drop|rebound|rise|increase|growth|recovery)')
_SHAPE = re.compile(r'\b(?:the\s+)?source\s+(?:describes|reports|presents)\s+(?:a|an|the)\s+'
    rf'(?P<shape>{_NOUN}\s+(?:and(?:\s+then)?|followed\s+by)\s+(?:(?:a|an|the)\s+)?{_NOUN})\b', re.I)
_AMOUNT = re.compile(r'\d|[%$€£¥]|\b(?:percent|USD|RMB|CNY|EUR|GBP|million|billion|thousand)\b', re.I)


def source_shape_noun(text, start, end, *, metric_spans, periods):
    """Keep literal, unbound qualitative shapes with the source meaning reviewer.

    A bound metric subject, monetary/rate token, new date or independent verb predicate
    never enters this path. This grants no source verdict: the complete page
    still requires its independent source review.
    """
    match = _SHAPE.search(text)
    if not match or not (match.start('shape') <= start < end <= match.end('shape')):
        return False
    # A known metric may occur as the denominator of an unbound source ratio,
    # rather than be the subject of this nominal description. Ordinary known
    # metric subjects remain on their numeric binding route.
    if any(left < match.end('shape') or not re.search(r'\b(?:share|proportion|ratio)\b',
            text[match.end('shape'):left], re.I) for left, _ in metric_spans):
        return False
    checked = bound_period_dates(text, periods, mask=True)
    if checked is None:
        return False
    for period in sorted(set(periods), key=len, reverse=True):
        checked = re.sub(r'(?<!\w)' + re.escape(period) + r'(?!\w)', ' ', checked, flags=re.I)
    return not _AMOUNT.search(checked)
