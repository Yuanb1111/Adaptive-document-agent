"""Compare literal calendar labels across languages without treating months as amounts."""
import re
from datetime import date

_MONTHS = ('January February March April May June July August September October November December').split()
_MONTH_NUMBER = {name.casefold(): i for i, name in enumerate(_MONTHS, 1)}
_MONTH_NUMBER.update({name[:3].casefold(): i for i, name in enumerate(_MONTHS, 1)})
_MONTH = '|'.join(sorted(_MONTH_NUMBER, key=len, reverse=True))
_DATED_PERIOD = re.compile(
    rf'\b(?:(?P<month>{_MONTH})\.?\s+(?P<day>\d{{1,2}}),?|'
    rf'(?P<day_first>\d{{1,2}})\s+(?P<month_last>{_MONTH})\.?)\s+'
    r'(?P<year>(?:19|20)\d{2})(?![\w-])', re.I)
_COORDINATED_PERIOD = re.compile(_DATED_PERIOD.pattern +
    r'(?P<coordinated_years>(?:(?:,\s*(?:and\s+)?|\s+and\s+)'
    r'(?:19|20)\d{2}(?![\w-]))+)'
    r'(?!\s*(?:,\s*(?:and\s+)?|\s+and\s+)(?:19|20)\d{2})'
    r'(?=\s*(?:[,.;:)]|$|\b(?:and|respectively|were|was|are|is|had|have|has|which|for|as)\b))', re.I)
_ISO_PERIOD = re.compile(r'(?<![\w.-])(?:19|20)\d{2}-\d{2}-\d{2}(?![\w-]|\.\w)')
_ISO_RANGE = re.compile(r'(?<![\w.-])(?P<start>(?:19|20)\d{2}-\d{2}-\d{2})-to-'
                        r'(?P<end>(?:19|20)\d{2}-\d{2}-\d{2})(?![\w-]|\.\w)', re.I)
_MONTH_YEAR=re.compile(rf'\b(?P<month>{_MONTH})\.?\s+(?P<year>(?:19|20)\d{{2}})\b',re.I)
_SCOPED_MONTH_DAY=re.compile(
    rf'\b(?P<prefix>(?:as of|at|on|by|since|from|to)\s+)'
    rf'(?P<month>{_MONTH})\.?\s+(?P<day>\d{{1,2}})\b'
    r'(?=\s*(?:[.;)]|,(?!\s*\d)|$|\b(?:had|has|have|was|were|is|are|as|and|or|to|until)\b))',re.I)
_SCOPED_YEAR_RANGE=re.compile(r'\bthe\s+(?P<first>(?:19|20)\d{2})[–-](?P<last>(?:19|20)?\d{2})'
    r'(?=\s+(?:build|build-up|increase|decrease|decline|growth|rise|reduction)\b)',re.I)
_DATES = re.compile(
    rf'(?i)(?<![\w.])(?P<iso_year>(?:19|20)\d{{2}})-(?P<iso_month>\d{{2}})-(?P<iso_day>\d{{2}})(?![\w-]|\.\w)'
    rf'|\b(?P<month>{_MONTH})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b'
    rf'|\b(?P<day_first>\d{{1,2}})\s+(?P<month_last>{_MONTH})\.?\b'
    r'|(?P<cn_month>1[0-2]|[1-9])\s*月\s*(?P<cn_day>3[01]|[12]\d|[1-9])\s*日')


def literal_calendar_dates(text: str) -> set[str]:
    """Extract complete literal calendar coordinates, without expanding period labels."""
    dates = set()
    for match in _ISO_PERIOD.finditer(text):
        try:
            dates.add(date.fromisoformat(match[0]).isoformat())
        except ValueError:
            pass
    for match in _DATED_PERIOD.finditer(text):
        try:
            dates.add(date(int(match['year']),
                _MONTH_NUMBER[(match['month'] or match['month_last']).casefold()],
                int(match['day'] or match['day_first'])).isoformat())
        except ValueError:
            pass
    for match in _COORDINATED_PERIOD.finditer(text):
        for year in re.findall(r'(?:19|20)\d{2}',match['coordinated_years']):
            try:
                dates.add(date(int(year),
                    _MONTH_NUMBER[(match['month'] or match['month_last']).casefold()],
                    int(match['day'] or match['day_first'])).isoformat())
            except ValueError:
                pass
    return dates


def mask_bound_month_years(text,periods,source_text=''):
    """A month/year may project a bound date, but never supplies a missing day."""
    owners={value[:7] for period in periods for value in literal_calendar_dates(period or '')}
    owners.update(f"{m['year']}-{_MONTH_NUMBER[m['month'].casefold()]:02d}"
                  for m in _MONTH_YEAR.finditer(source_text))
    return _MONTH_YEAR.sub(lambda m:' ' if
        f"{m['year']}-{_MONTH_NUMBER[m['month'].casefold()]:02d}" in owners else m[0],text)


def mask_scoped_month_days(text,scope,proof):
    """Recognize a qualitative date reference to one complete scoped source date."""
    scoped_dates=literal_calendar_dates(scope)
    dates_by_month_day={}
    for coordinate in literal_calendar_dates(proof):
        dates_by_month_day.setdefault(coordinate[5:],set()).add(coordinate)

    def replace(match):
        month=_MONTH_NUMBER[match['month'].casefold()]
        dates=dates_by_month_day.get(f"{month:02d}-{int(match['day']):02d}",set())
        if len(dates)==1 and dates<=scoped_dates:
            return match['prefix']+' '
        return match[0]

    return _SCOPED_MONTH_DAY.sub(replace,text)


def mask_scoped_year_ranges(text,scope,proof):
    """Recognize event year ranges from exact same-day dates in a single proof sentence."""
    if not _SCOPED_YEAR_RANGE.search(text):
        return text
    coordinates=literal_calendar_dates(scope)
    proof_sentences=[literal_calendar_dates(sentence) for sentence in re.split(r'(?<=[.!?])\s+',proof)]

    def replace(match):
        start=[coordinate for coordinate in coordinates if coordinate[:4]==match['first']]
        last=match['last']
        end=[coordinate for coordinate in coordinates if coordinate[:4].endswith(last)]
        if len(last)==2 and len(coordinates)!=2:
            return match[0]
        if len(start)==len(end)==1 and start[0]<end[0] and start[0][5:]==end[0][5:] and any(
                {start[0],end[0]}<=dates for dates in proof_sentences):
            return 'the '
        return match[0]

    return _SCOPED_YEAR_RANGE.sub(replace,text)


def bound_period_dates(text, periods, *, mask=False):
    """Normalize complete dates only if the exact date is a selected source period."""
    owners = set(periods)
    # Source periods may themselves use spelled month names. Compare complete
    # calendar identities in either spelling, never expand FY/interim labels.
    for period in tuple(owners):
        if _DATED_PERIOD.fullmatch(period or '') or _COORDINATED_PERIOD.fullmatch(period or ''):
            owners.update(literal_calendar_dates(period))
    unmatched = False
    def spelled(match):
        nonlocal unmatched
        try:
            value = date(int(match['year']), _MONTH_NUMBER[(match['month'] or match['month_last']).lower()],
                         int(match['day'] or match['day_first'])).isoformat()
        except ValueError:
            unmatched = True
            return match[0]
        if value not in owners:
            unmatched = True
        return value if value in owners else match[0]
    # The explicit word "to" connects two complete dates; it is not part of
    # either date or an identifier. Both endpoints still require source owners.
    normalized = _ISO_RANGE.sub(lambda m: m['start'] + ' to ' + m['end'], text)
    def coordinated(match):
        nonlocal unmatched
        years=[match['year'],*re.findall(r'(?:19|20)\d{2}',match['coordinated_years'])]
        try:
            coordinates=[date(int(year),
                _MONTH_NUMBER[(match['month'] or match['month_last']).casefold()],
                int(match['day'] or match['day_first'])).isoformat() for year in years]
        except ValueError:
            unmatched=True
            return match[0]
        if not set(coordinates)<=owners:
            unmatched=True
            return match[0]
        return ', '.join(coordinates)
    normalized = _COORDINATED_PERIOD.sub(coordinated,normalized)
    normalized = _DATED_PERIOD.sub(spelled, normalized)
    if mask:
        if unmatched or any(m[0] not in owners for m in _ISO_PERIOD.finditer(normalized)):
            return None
        return _ISO_PERIOD.sub(' ', normalized)
    return normalized


def period_identity(period: str) -> str:
    """Compare an exact calendar spelling without changing its retained source label."""
    return re.sub(r'\s+','',bound_period_dates(period,[period])).casefold()


def split_calendar_dates(text: str) -> tuple[str, set[str]]:
    """Keep years and date identity; strip only explicit month/day spellings.

    Durations, prices and bare numbers remain quantitative claims. Date tokens
    also reject a changed month or day instead of authorizing arbitrary dates.
    """
    dates = set()

    def replace(match):
        if match['iso_year']:
            try:
                value = date(int(match['iso_year']), int(match['iso_month']), int(match['iso_day']))
            except ValueError:
                return match[0]
            dates.add(f'calendar:{value.month:02d}-{value.day:02d}')
            return match['iso_year']  # The year remains a source-checked claim.
        month = (int(match['cn_month']) if match['cn_month'] else
                 _MONTH_NUMBER[(match['month'] or match['month_last']).casefold()])
        day = int(match['day'] or match['day_first'] or match['cn_day'])
        try:
            date(2000, month, day)
        except ValueError:
            return match[0]
        dates.add(f'calendar:{month:02d}-{day:02d}')
        return ' '

    return _DATES.sub(replace, text), dates
