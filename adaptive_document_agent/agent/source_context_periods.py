"""Recognize literal source timing without licensing measured values or new periods."""
import re

from adaptive_document_agent.services.calendar_claims import bound_period_dates,literal_calendar_dates
from adaptive_document_agent.services.number_words import cardinal_claim_text

_YEAR=r'(?:19|20)\d{2}'
_YEARS=rf'{_YEAR}(?:\s*(?:,\s*(?:and\s+)?|and\s+|to\s+|[–-]\s*){_YEAR})*'
_REFERENCE=re.compile(rf'\b(?:in|during|for|from|to|since|until|through|between|and)\s+(?P<years>{_YEARS})'
    r'(?=\s*(?:[,.;:]|$|\b(?:and|then|as|when|because|due|primarily|while|during|from|to|for|in|with|onwards?|forward)\b))',re.I)
_LEADING=re.compile(rf'(?:^|(?<=;))\s*(?:(?:For|Within|During|In)\s+)?(?P<years>{_YEARS})'
    r'(?=\s*(?:[,.;:]|$|\band\b))',re.I)
_ENDED=re.compile(r'\b(?:the\s+)?(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[1-9]|1[0-2])'
    r'\s+months?\s+ended\s+(?:19|20)\d{2}-\d{2}-\d{2}\b',re.I)
_HORIZON=re.compile(r'\b(?:next|following)\s+(?P<number>\d+)\s+'
    r'(?P<unit>years?|months?|weeks?|days?|hours?)\b',re.I)
_HORIZON_COPY=re.compile(r'\b(?:next|following)\s+'
    r'(?P<number>\d+|[A-Za-z]+(?:[\s-]+[A-Za-z]+){0,6}?)\s+'
    r'(?P<unit>years?|months?|weeks?|days?|hours?)\b',re.I)
_YEAR_EVENT=re.compile(rf'\bthe\s+(?P<years>{_YEAR})\s+'
    r'(?=(?:(?![A-Za-z]*s\b)[A-Za-z]+[\s-]+){0,5}'
    r'(?:increases?|decreases?|growth|declines?|expansions?|reductions?|recover(?:y|ies)|slowdowns?)\b)',re.I)
_YEAR_REPORT=re.compile(rf'\bthe\s+(?P<years>{_YEAR})\s+'
    r'(?=(?:balance|level|result|figure|position|reporting\s+period)\b)',re.I)
_REPORTING_ENDED=re.compile(r'\b(?P<count>\d+)\s+(?P<unit>months?|weeks?|days?|years?)\s+'
    r'ended\s+(?P<date>(?:19|20)\d{2}-\d{2}-\d{2})\b',re.I)
_REPORTING_REFERENCE=re.compile(r'\b(?:during|within|over|for)\s+(?:the\s+)?'
    r'(?P<count>[A-Za-z]+(?:[\s-]+[A-Za-z]+){0,6}?)'
    r'[\s-]+(?P<unit>months?|weeks?|days?|years?)[\s-]+period\b',re.I)
_FISCAL_LABEL=re.compile(r'\b(?:FY|\d{1,2}M|Q[1-4]-?|[12]H-?)(?:19|20)\d{2}E?\b',re.I)


def scope_period_feedback(scope,periods):
    """Explain an unbound label without guessing a fiscal/calendar conversion."""
    from adaptive_document_agent.services.calendar_claims import period_identity
    known={period_identity(p) for p in periods if p}
    unknown=sorted({m[0] for m in _FISCAL_LABEL.finditer(scope) if period_identity(m[0]) not in known})
    if not unknown:return None
    return dict(unbound_scope_period_labels=unknown,exact_bound_period_labels=sorted({p for p in periods if p}),
        semantic_approval=False,correction_rule='Use only the exact labels bound to this page, or '
        'preserve source-only discussion timing literally with its own proof. Do not convert '
        'dated snapshots into fiscal/interim labels or infer calendar dates from fiscal labels. '
        'Reviewer requests cannot authorize a missing period binding.')


def mask_reporting_period_references(text,proof,scope):
    """Reconcile a worded reporting duration with its literal dated source scope.

    A measured cycle duration, another count/unit, or an unspecified end date
    cannot borrow it. No fiscal/interim label is expanded to a calendar date.
    """
    dates=literal_calendar_dates(proof)
    source=cardinal_claim_text(bound_period_dates(proof,dates))
    scope_dates=literal_calendar_dates(scope)&dates
    owned={(m['count'],m['unit'].casefold().rstrip('s')) for m in _REPORTING_ENDED.finditer(source)
           if m['date'] in scope_dates}
    return _REPORTING_REFERENCE.sub(lambda m:' ' if
        (cardinal_claim_text(m['count']),m['unit'].casefold().rstrip('s')) in owned else m[0],text)


def mask_source_horizons(text,proof):
    """Only an explicitly future duration with the same source count and unit."""
    source=cardinal_claim_text(proof)
    owned={(m['number'],m['unit'].casefold().rstrip('s')) for m in _HORIZON.finditer(source)}
    return _HORIZON_COPY.sub(lambda m:' ' if
        (cardinal_claim_text(m['number']),m['unit'].casefold().rstrip('s')) in owned
        else m[0],text)


def mask_source_periods(text,proof,*,scope=False,periods=()):
    """Mask only source-owned temporal references; retain other numeric tokens.

    A duration is eligible only as a complete literal months-ended date phrase.
    Bare years need temporal grammar in both source and copy. Neither source
    amounts resembling years nor unknown fiscal/interim labels become periods.
    """
    dates=literal_calendar_dates(proof)
    normalize=lambda value:' '.join(bound_period_dates(value,[*dates,*periods]).split())
    source=normalize(proof)
    words=normalize(text)
    years={year for match in _REFERENCE.finditer(source)
           for year in re.findall(_YEAR,match['years'])}
    years.update(value[:4] for value in dates)
    def year_ref(match):
        if not set(re.findall(_YEAR,match['years']))<=years:return match[0]
        start,end=match.span('years')
        return match[0][:start-match.start()]+' '*(end-start)+match[0][end-match.start():]
    words=_REFERENCE.sub(year_ref,words)
    words=_YEAR_EVENT.sub(year_ref,words)
    words=_YEAR_REPORT.sub(year_ref,words)
    if scope:words=_LEADING.sub(year_ref,words)
    words=_ENDED.sub(lambda m:' ' if m[0].casefold() in source.casefold() else m[0],words)
    from adaptive_document_agent.services.calendar_claims import mask_bound_month_years
    words=mask_bound_month_years(words,[*periods,*dates],proof)
    return words
