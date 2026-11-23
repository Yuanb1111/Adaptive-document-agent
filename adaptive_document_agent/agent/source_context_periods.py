"""Recognize literal source timing without licensing measured values or new periods."""
import re

from adaptive_document_agent.services.calendar_claims import bound_period_dates,literal_calendar_dates
from adaptive_document_agent.services.number_words import cardinal_claim_text

_YEAR=r'(?:19|20)\d{2}'
_YEARS=rf'{_YEAR}(?:\s*(?:,\s*(?:and\s+)?|and\s+|to\s+|[–-]\s*){_YEAR})*'
_REFERENCE=re.compile(rf'\b(?:in|during|for|from|to|since|until|through|between|and)\s+(?P<years>{_YEARS})'
    r'(?=\s*(?:[,.;:]|$|\b(?:and|then|as|when|because|due|primarily|while|during|from|to|for|in|with|onwards?|forward)\b))',re.I)
_YEAR_COMPARISON=re.compile(rf'(?<![\w-]){_YEAR}\s+compared\s+with\s+{_YEAR}'
    r'(?=\s*(?:[,.;:]|$|\b(?:as|when|because|which|while|was|were)\b))',re.I)
_PROVED_YEAR_COMPARISON=re.compile(r'\b(?:in|during|for)\s+(?P<pair>'+_YEAR_COMPARISON.pattern+r')',re.I)
_CAUSAL_PREDICATE=r'(?:contributed|contributes|affected|affects|supported|supports|led|leads)'
_SOURCE_SINCE_YEAR=re.compile(rf'\bsince\s+(?P<year>{_YEAR})'
    rf'(?=\s*(?:[,.;:]|$|\b{_CAUSAL_PREDICATE}\b))',re.I)
_SOURCE_IN_YEAR_BEFORE_PREDICATE=re.compile(rf'\bin\s+(?P<year>{_YEAR})'
    rf'(?=\s+{_CAUSAL_PREDICATE}\b)',re.I)
_LEADING=re.compile(rf'(?:^|(?<=;))\s*(?:(?:For|Within|During|In)\s+)?(?P<years>{_YEARS})'
    r'(?=\s*(?:[,.;:]|$|\band\b))',re.I)
_ENDED=re.compile(r'\b(?:the\s+)?(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[1-9]|1[0-2])'
    r'\s+months?\s+ended\s+(?:19|20)\d{2}-\d{2}-\d{2}\b',re.I)
_HORIZON=re.compile(r'\b(?:next|following)\s+(?P<number>\d+)\s+'
    r'(?P<unit>years?|months?|weeks?|days?|hours?)\b',re.I)
_HORIZON_COPY=re.compile(r'\b(?:next|following)\s+'
    r'(?P<number>\d+|[A-Za-z]+(?:[\s-]+[A-Za-z]+){0,6}?)\s+'
    r'(?P<unit>years?|months?|weeks?|days?|hours?)\b',re.I)
_YEAR_EVENT=re.compile(rf'\b(?:the|links?|attributes?|describes?)\s+(?P<years>{_YEAR})\s+'
    r'(?=(?:(?!(?:interim|annual|fiscal|quarterly|semiannual|half-year|full-year|[A-Za-z]*s)\b)'
    r'[A-Za-z]+[\s-]+){0,5}'
    r'(?:increases?|decreases?|growth|declines?|expansions?|reductions?|recover(?:y|ies)|'
    r'slowdowns?|lengthening|prolongation|shortening)\b)',re.I)
_YEAR_REPORT=re.compile(rf'\bthe\s+(?P<years>{_YEAR})\s+'
    r'(?=(?:balance|level|result|figure|position|reporting\s+period)\b)',re.I)
_REPORTING_ENDED=re.compile(r'\b(?P<count>\d+)\s+(?P<unit>months?|weeks?|days?|years?)\s+'
    r'ended\s+(?P<date>(?:19|20)\d{2}-\d{2}-\d{2})\b',re.I)
_REPORTING_REFERENCE=re.compile(r'\b(?:during|within|over|for)\s+(?:the\s+)?'
    r'(?P<count>[A-Za-z]+(?:[\s-]+[A-Za-z]+){0,6}?)'
    r'[\s-]+(?P<unit>months?|weeks?|days?|years?)[\s-]+period\b',re.I)
_REPORTING_COMPARISON=re.compile(r'\b(?:in|during|within|over|for)\s+(?:this|the)\s+'
    r'(?P<count>[A-Za-z]+)'
    r'[\s-]+(?P<unit>months?|weeks?|days?|years?)[\s-]+comparison\b',re.I)
_LATEST_MONTHS_PERIOD=re.compile(r'\b(?:in|during|within|over|for)\s+(?:the\s+)?latest\s+'
    r'(?P<count>[A-Za-z]+)[\s-]+(?P<unit>months?)\s+period\b',re.I)
_FISCAL_LABEL=re.compile(r'\b(?:FY|\d{1,2}M|Q[1-4]-?|[12]H-?)(?:19|20)\d{2}E?\b',re.I)


def scope_period_feedback(scope,periods):
    """Explain an unbound label without guessing a fiscal/calendar conversion."""
    from adaptive_document_agent.services.calendar_claims import period_identity
    known={period_identity(p) for p in periods if p}
    unknown=sorted({m[0] for m in _FISCAL_LABEL.finditer(scope) if period_identity(m[0]) not in known})
    if not unknown:return None
    return dict(unbound_scope_period_labels=unknown,exact_bound_period_labels=sorted({p for p in periods if p}),
        semantic_approval=False,
        correction_rule='Keep every still-applicable exact_bound_period_label in scope. Replace an '
        'unbound interim shorthand with a complete literal months-ended discussion window only when '
        'this item’s own contiguous proof gives the same duration and end date for the same discussion. '
        'Keep that full phrase verbatim and separate from bound annual or exact-date labels. For any '
        'other unsupported shorthand, or when the proof does not establish that same complete window, '
        'remove the shorthand and keep only genuinely applicable exact bound labels.',
        source_only_timing_rule='A complete literal months-ended phrase in this item’s own proof may '
        'remain in source_context.scope as a source-only discussion window alongside separately stated '
        'bound annual labels. It is not a bound interim-period label. Do not replace the full window with '
        'its end-date snapshot, normalize or abbreviate it to an unbound interim label, or use it to bind '
        'an amount, observation, calculation, or comparison. Any distinct qualitative timing must be '
        'supported by its own exact quote and must describe the same source discussion. Never convert a '
        'dated snapshot into a fiscal/interim label or infer a calendar date from a fiscal label.',
        reviewer_rule='Reviewer requests cannot authorize a missing period binding.')


def mask_reporting_period_references(text,proof,scope):
    """Reconcile a worded reporting duration with its literal dated source scope.

    A measured cycle duration, another count/unit, or an unspecified end date
    cannot borrow it. No fiscal/interim label is expanded to a calendar date.
    """
    dates=literal_calendar_dates(proof)
    source=cardinal_claim_text(bound_period_dates(proof,dates))
    scope_dates=literal_calendar_dates(scope)&dates
    def duration(match):
        return cardinal_claim_text(match['count']),match['unit'].casefold().rstrip('s')

    source_ends={(duration(m),m['date']) for m in _REPORTING_ENDED.finditer(source) if m['date'] in scope_dates}
    owned={key for key,_ in source_ends}
    text=_REPORTING_REFERENCE.sub(lambda m:' ' if duration(m) in owned else m[0],text)
    scope_text=cardinal_claim_text(bound_period_dates(scope,dates))
    compared_ends={}
    for match in _REPORTING_ENDED.finditer(scope_text):
        key=duration(match)
        if (key,match['date']) in source_ends:
            compared_ends.setdefault(key,set()).add(match['date'])
    text=_REPORTING_COMPARISON.sub(lambda m:' ' if
        len(compared_ends.get(duration(m),()))==2 else m[0],text)
    # "latest six-month period" is only a reference to an explicitly owned
    # full window when this item's exact scope selects one complete window and
    # that window is the latest matching duration stated in its own proof.
    proof_windows={(duration(match),match['date'])
        for match in _REPORTING_ENDED.finditer(source)}
    def latest_period(match):
        key=duration(match)
        applicable=compared_ends.get(key,set())
        proved={date for candidate,date in proof_windows if candidate==key}
        if len(applicable)==1 and proved and max(proved)==next(iter(applicable)):
            return ' '
        return match[0]
    return _LATEST_MONTHS_PERIOD.sub(latest_period,text)


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
    source_references=list(_REFERENCE.finditer(source))
    years={year for match in source_references
           for year in re.findall(_YEAR,match['years'])}
    years.update(value[:4] for value in dates)
    def year_ref(match):
        if not set(re.findall(_YEAR,match['years']))<=years:return match[0]
        start,end=match.span('years')
        return match[0][:start-match.start()]+' '*(end-start)+match[0][end-match.start():]
    # A source-owned comparison may be repeated in its scope or description.
    # Two unrelated year tokens or counts resembling years supply no pair.
    compared={match['pair'].casefold() for match in _PROVED_YEAR_COMPARISON.finditer(source)}
    words=_YEAR_COMPARISON.sub(lambda match:' ' if match[0].casefold() in compared else match[0],words)
    since_years={match['year'] for match in _SOURCE_SINCE_YEAR.finditer(source)}
    words=_SOURCE_SINCE_YEAR.sub(lambda match:'since ' if match['year'] in since_years else match[0],words)
    proved_in_year={match['years'] for match in source_references
                    if match[0].casefold().startswith('in ') and re.fullmatch(_YEAR,match['years'])}
    proved_in_year.update(match['year'] for match in _SOURCE_IN_YEAR_BEFORE_PREDICATE.finditer(source))
    words=_SOURCE_IN_YEAR_BEFORE_PREDICATE.sub(lambda match:'in ' if
        match['year'] in proved_in_year else match[0],words)
    # Mask the complete leading range before the general reference rule can
    # consume only its second endpoint after "to".
    if scope:words=_LEADING.sub(year_ref,words)
    words=_REFERENCE.sub(year_ref,words)
    words=_YEAR_EVENT.sub(year_ref,words)
    words=_YEAR_REPORT.sub(year_ref,words)
    words=_ENDED.sub(lambda m:' ' if m[0].casefold() in source.casefold() else m[0],words)
    from adaptive_document_agent.services.calendar_claims import mask_bound_month_years
    words=mask_bound_month_years(words,[*periods,*dates],proof)
    return words
