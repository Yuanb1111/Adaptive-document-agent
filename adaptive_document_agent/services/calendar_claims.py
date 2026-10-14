"""Compare literal calendar labels across languages without treating months as amounts."""
import re
from datetime import date

_MONTHS = ('January February March April May June July August September October November December').split()
_MONTH_NUMBER = {name.casefold(): i for i, name in enumerate(_MONTHS, 1)}
_MONTH_NUMBER.update({name[:3].casefold(): i for i, name in enumerate(_MONTHS, 1)})
_MONTH = '|'.join(sorted(_MONTH_NUMBER, key=len, reverse=True))
_DATES = re.compile(
    rf'(?i)\b(?P<month>{_MONTH})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b'
    rf'|\b(?P<day_first>\d{{1,2}})\s+(?P<month_last>{_MONTH})\.?\b'
    r'|(?P<cn_month>1[0-2]|[1-9])\s*月\s*(?P<cn_day>3[01]|[12]\d|[1-9])\s*日')


def split_calendar_dates(text: str) -> tuple[str, set[str]]:
    """Keep years and date identity; strip only explicit month/day spellings.

    Durations, prices and bare numbers remain quantitative claims. Date tokens
    also reject a changed month or day instead of authorizing arbitrary dates.
    """
    dates = set()

    def replace(match):
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
