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
_ISO_PERIOD = re.compile(r'(?<![\w.-])(?:19|20)\d{2}-\d{2}-\d{2}(?![\w-]|\.\w)')
_ISO_RANGE = re.compile(r'(?<![\w.-])(?P<start>(?:19|20)\d{2}-\d{2}-\d{2})-to-'
                        r'(?P<end>(?:19|20)\d{2}-\d{2}-\d{2})(?![\w-]|\.\w)', re.I)
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
    return dates


def bound_period_dates(text, periods, *, mask=False):
    """Normalize complete dates only if the exact date is a selected source period."""
    owners = set(periods)
    # Source periods may themselves use spelled month names. Compare complete
    # calendar identities in either spelling, never expand FY/interim labels.
    for period in tuple(owners):
        match = _DATED_PERIOD.fullmatch(period or '')
        if match:
            try:
                owners.add(date(int(match['year']),
                    _MONTH_NUMBER[(match['month'] or match['month_last']).lower()],
                    int(match['day'] or match['day_first'])).isoformat())
            except ValueError:
                pass
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
    normalized = _DATED_PERIOD.sub(spelled, normalized)
    if mask:
        if unmatched or any(m[0] not in owners for m in _ISO_PERIOD.finditer(normalized)):
            return None
        return _ISO_PERIOD.sub(' ', normalized)
    return normalized


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
