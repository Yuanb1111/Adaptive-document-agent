"""Bind an explicit list of raw levels and dates to every written source pair."""
import re
from decimal import Decimal, InvalidOperation

_YEAR=r'(?:19|20)\d{2}'
_PERIOD=rf'(?:{_YEAR}-\d{{2}}-\d{{2}}|(?:FY\s*|[1369]M\s*|[12]H\s*|Q[1-4]\s*)?{_YEAR})'
_NUMBER=r'[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_PAIR=re.compile(rf'(?<![\w.])(?P<value>\({_NUMBER}\)|{_NUMBER})\s*'
    rf'(?:(?:as\s+of|at|in|on)\s+|\(\s*)(?P<period>{_PERIOD})\b\s*\)?',re.I)
_MENTION=re.compile(rf'\b{_PERIOD}\b',re.I)
_SEPARATOR=re.compile(r'\s*(?:\(\s*(?:un)?audited\s*\)\s*)?'
    r'(?:,\s*(?:and\s*)?|and\s+)',re.I)


def explicit_dated_levels(text):
    """Recognize a single uninterrupted level list owning every stated period."""
    pairs=list(_PAIR.finditer(text))
    if len(pairs)<3 or not all(_SEPARATOR.fullmatch(text[a.end():b.start()])
                               for a,b in zip(pairs,pairs[1:])):
        return None
    if not all(any(p.start('period')<=m.start()<m.end()<=p.end('period') for p in pairs)
               for m in _MENTION.finditer(text)):
        return None
    return text[pairs[0].start():pairs[-1].end()],[(p['value'],p['period']) for p in pairs]


def _number(text):
    text=text.strip().replace(',','').replace('−','-')
    if text.startswith('(') and text.endswith(')'):
        return -Decimal(text[1:-1])
    return Decimal(text)


def dated_level_segments(text,observations):
    """Every raw level must match its own exact date before any direction check."""
    explicit=explicit_dated_levels(text)
    if explicit is None:
        return None
    normalize=lambda value:re.sub(r'\s+','',value or '').casefold()
    indices=[]
    for amount,period in explicit[1]:
        matches=[i for i,o in enumerate(observations) if normalize(o.period)==normalize(period)]
        if len(matches)!=1:
            return []
        index=matches[0]
        try:
            if _number(amount)!=_number(observations[index].raw_value):
                return []
        except InvalidOperation:
            return []
        indices.append(index)
    if any(b!=a+1 for a,b in zip(indices,indices[1:])):
        return []
    return [observations[a:b+1] for a,b in zip(indices,indices[1:])]
