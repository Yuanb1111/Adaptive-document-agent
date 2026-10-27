"""Literal snapshot-date evidence, not semantic column ownership or assurance."""
from datetime import date
import re

_MONTHS = 'January February March April May June July August September October November December'.split()
_MONTH = '(?:' + '|'.join(_MONTHS) + ')'
_YEAR = r'(?:19|20)\d{2}'
_DAY_MONTH = re.compile(rf'\b(?:(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH})'
                           rf'|(?P<month_first>{_MONTH})\s+(?P<day_last>\d{{1,2}}))\b', re.I)
_YEAR_ROW = re.compile(rf'\s*(?:Notes?\s+)?{_YEAR}(?:\s+{_YEAR}){{1,23}}\s*', re.I)
_YEAR_LIST = re.compile(rf'\s*,?\s*(?P<years>{_YEAR}(?:(?:\s*,\s*(?:and\s+)?|\s+and\s+){_YEAR})*)\b', re.I)


def _month_day(match):
    month = match['month'] or match['month_first']
    day = int(match['day'] or match['day_last'])
    return next(i for i, name in enumerate(_MONTHS, 1) if name.casefold() == month.casefold()), day


def _shared_header_components(text):
    """Recognize complete date-only tiers followed by a year-only table row.

    Flattened PDF text does not prove which date tier owns which year column.
    Return literal components only; the mandatory independent source reviewer
    still has to establish that the requested date belongs to the exact amount.
    No Cartesian-product periods or assurance records are generated here.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not 2 <= len(lines) <= 5 or not _YEAR_ROW.fullmatch(lines[-1]):
        return None
    tiers = ' '.join(lines[:-1])
    if not re.search(r'\bas\s+(?:at|of)\b', tiers, re.I):
        return None
    dates = list(_DAY_MONTH.finditer(tiers))
    remainder = _DAY_MONTH.sub('', tiers)
    remainder = re.sub(r'\bas\s+(?:at|of)\b', '', remainder, flags=re.I)
    if not dates or remainder.strip(' \t,:;|()'):
        return None
    return {int(y) for y in re.findall(_YEAR, lines[-1])}, {_month_day(m) for m in dates}


def snapshot_period_in_header(period, text):
    """Check complete dates, shared-year lists and literal multiline table tiers."""
    try:
        expected = date.fromisoformat(period)
    except ValueError:
        return False
    if re.search(r'(?<![\d-])' + re.escape(period) + r'(?![\d-])', text):
        return True
    # A literal quote may also retain its title, units and qualification rows.
    # Locate a continuous header block inside it, without joining date/year
    # fragments across intervening prose, amounts or another table.
    lines = [line for line in text.splitlines() if line.strip()]
    for end, line in enumerate(lines):
        if not _YEAR_ROW.fullmatch(line):
            continue
        for start in range(max(0, end - 4), end):
            shared = _shared_header_components('\n'.join(lines[start:end + 1]))
            if shared is not None:
                years, month_days = shared
                if expected.year in years and (expected.month, expected.day) in month_days:
                    return True
    for match in _DAY_MONTH.finditer(text):
        years = _YEAR_LIST.match(text, match.end())
        if years is None or _month_day(match) != (expected.month, expected.day):
            continue
        if str(expected.year) in re.findall(_YEAR, years['years']):
            return True
    return False


PERIOD_HEADER_INSTRUCTIONS = (
    'A snapshot date may use a shared month/day followed by several explicit years, or '
    'separate month/day tiers above a year row. Quote the complete literal header with '
    'its line breaks; never fabricate an ISO date inside a quotation. Literal date '
    'components are only a preflight check, never proof of column ownership. Independently '
    'verify which month/day tier and year column own the exact signed amount; do not '
    'cross-pair a date with another column year or use assurance prose as a substitute '
    'for the covered original table header. ')
