"""Bind explicitly calculated native count changes to exact Python results."""
import re
from decimal import Decimal,InvalidOperation

_PERIOD=r'(?:FY\s*|[1-9]M\s*|1[0-2]M\s*|Q[1-4]\s*|[12]H\s*)?(?:19|20)\d{2}(?:-\d{2}-\d{2})?E?'
_NUMBER=r'[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_LABEL=r'\b(?:calculated|computed|recalculated|recomputed)\s+(?:signed\s+)?(?P<kind>change|difference|increase|decrease)'
_RANGE=rf'from\s+(?P<start>{_PERIOD})\s+to\s+(?P<end>{_PERIOD})\b'
_AFTER=re.compile(_LABEL+rf'\s+(?:was|is|of)\s*(?P<number>{_NUMBER})'
    rf'(?:\s+(?P<unit>[A-Za-z]+))?\s+{_RANGE}',re.I)
_BEFORE=re.compile(_LABEL+rf'\s+{_RANGE}\s+(?:was|is|of)\s*(?P<number>{_NUMBER})'
    r'(?:\s+(?P<unit>[A-Za-z]+))?',re.I)


def _raw(item):
    value=item.raw_value.strip().replace(',','').replace('−','-')
    if value.startswith('(') and value.endswith(')'):
        value='-'+value[1:-1].strip()
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',value):raise InvalidOperation
    parsed=Decimal(value)
    if parsed!=Decimal(str(item.value)):raise InvalidOperation
    return parsed


def checked_count_changes(text,observations,calculations):
    """Yield claim/support/IDs; never infer a metric, interval, scale or unit."""
    counts={o.id:o for o in observations if o.value is not None and o.unit_family=='count'
            and o.unit_scale==1 and o.validation_status=='valid' and o.evidence}
    if not counts:return
    catalog=[c for c in calculations if c.get('kind') in {'absolute_change','yoy_absolute_change'}
        and not c.get('currency') and len(c.get('observation_ids',()))==2
        and set(c['observation_ids'])<=counts.keys()]
    normalize=lambda value:re.sub(r'\s+','',value).casefold()
    matches=sorted([*_AFTER.finditer(text),*_BEFORE.finditer(text)],key=lambda m:m.start())
    seen=set()
    for match in matches:
        if match.span('number') in seen:continue
        seen.add(match.span('number'))
        sentences=re.split(r'(?<=[.!?])\s+',text[:match.start()])
        subject=sentences[-1]
        if re.fullmatch(r'\s*The\s+',subject,re.I) and len(sentences)>1:
            subject=sentences[-2]  # One explicit immediately preceding subject only.
        ends=[normalize(match['start']),normalize(match['end'])]
        eligible=[c for c in catalog if [normalize(c['periods'][0]),normalize(c['periods'][-1])]==ends
            and re.search(r'(?<!\w)'+re.escape(c['metric'])+r'(?!\w)',subject,re.I)]
        if len(eligible)!=1:
            yield match,False,set();continue
        calc=eligible[0];unit=(match['unit'] or '').casefold().rstrip('s')
        allowed={str(calc.get('unit','')).casefold().rstrip('s')}
        allowed.update(word.rstrip('s') for word in re.findall(r'[a-z]+',calc['metric'].casefold()))
        if unit and unit not in allowed:
            yield match,False,set();continue
        try:
            first,last=(counts[oid] for oid in calc['observation_ids'])
            delta=_raw(last)-_raw(first)
            claimed=Decimal(match['number'].replace(',','').replace('−','-'))
            kind=match['kind'].casefold()
            valid=delta==Decimal(str(calc['value']))
            if kind in {'increase','decrease'}:
                valid=valid and claimed>0 and (delta>0 if kind=='increase' else delta<0)
                delta=abs(delta)
            valid=valid and claimed==delta
        except (InvalidOperation,ValueError):
            valid=False
        yield match,bool(valid),{calc['id']} if valid else set()


def mask_checked_count_changes(text,observations,calculations):
    masked=list(text)
    for match,supported,_ in checked_count_changes(text,observations,calculations):
        if supported:
            start,end=match.span('number');masked[start:end]=' '*(end-start)
    return ''.join(masked)
