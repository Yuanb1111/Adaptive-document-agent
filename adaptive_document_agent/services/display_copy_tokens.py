"""Equivalent display spellings, without changing coefficients or source records."""
from collections import Counter
from datetime import date
import re

_MONTHS = 'January February March April May June July August September October November December'.split()
_MONTH = {name.casefold(): i for i, name in enumerate(_MONTHS, 1)}
_MONTH.update({name[:3].casefold(): i for i, name in enumerate(_MONTHS, 1)})
_MONTH_PATTERN = '|'.join(sorted(_MONTH, key=len, reverse=True))


def display_text(text):
    """PPT soft line breaks are layout, never literal audience-facing escapes."""
    return re.sub(r'_x000[bB]_', '\n', text).replace('\v', '\n')


def compact_display_periods(text):
    """Shorten only equivalent explicit date/period labels for narrow boxes."""
    text = display_text(text)
    def replace(m):
        try:
            return date(int(m[1]),int(m[2]),int(m[3])).isoformat()
        except ValueError:
            return m[0]
    text = re.sub(r'((?:19|20)\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日',replace,text)
    text = re.sub(r'((?:19|20)\d{2})\s*(?:财年|財年)',r'FY\1 ',text)
    return re.sub(r'((?:19|20)\d{2})年?\s*(上半年|下半年)',
                  lambda m: ('6M' if m[2]=='上半年' else 'H2')+m[1]+' ',text)


def compact_display_units(text):
    """Native quantity spelling may be shorter; prose and coefficients stay intact."""
    from .executive_brief import _MONEY_QUANTITY
    from .brief_table_evidence import canonical_quantity
    def replace(m):
        if m['open']:
            return m[0]
        currency, _, unit = canonical_quantity(m['prefix'] or m['suffix'] or '',m['value'],m['unit'])
        units={'thousand':'k','million':'m','billion':'bn','trillion':'trillion'}
        if currency not in {'rmb','usd','hkd','eur','gbp'} or unit not in units:
            return m[0]
        return currency.upper()+' '+(m['sign'] or '')+m['value']+units[unit]
    return _MONEY_QUANTITY.sub(replace,display_text(text))


def _dates(text):
    tokens = []
    def replace(year, month, day, original):
        try:
            tokens.append(date(int(year), int(month), int(day)).isoformat())
            return ' '
        except ValueError:
            return original
    text = re.sub(r'(?<!\d)((?:19|20)\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日',
                  lambda m: replace(m[1], m[2], m[3], m[0]), text)
    text = re.sub(r'(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)',
                  lambda m: replace(m[1], m[2], m[3], m[0]), text)
    text = re.sub(r'\b(\d{1,2})\s+(' + _MONTH_PATTERN + r')\s+((?:19|20)\d{2})\b',
                  lambda m: replace(m[3], _MONTH[m[2].casefold()], m[1], m[0]), text, flags=re.I)
    text = re.sub(r'\b(' + _MONTH_PATTERN + r')\s+(\d{1,2}),?\s+((?:19|20)\d{2})\b',
                  lambda m: replace(m[3], _MONTH[m[1].casefold()], m[2], m[0]), text, flags=re.I)
    def month(year, value):
        if not 1 <= int(value) <= 12:
            return None
        tokens.append(f'{int(year):04d}-{int(value):02d}')
        return ' '
    text = re.sub(r'((?:19|20)\d{2})年\s*(\d{1,2})月',
                  lambda m: month(m[1],m[2]) or m[0], text)
    text = re.sub(r'\b(' + _MONTH_PATTERN + r')\s+((?:19|20)\d{2})\b',
                  lambda m: month(m[2],_MONTH[m[1].casefold()]) or m[0], text, flags=re.I)
    return text, Counter(tokens)


def copy_tokens(text):
    """Equal dates, periods, signed coefficients and currency/scale counts.

    Chinese date order, fiscal/half-year labels and unit names may differ.
    No rescaling, rounding, conversion or deletion of repeated values is
    permitted. Meaning is independently model-reviewed.
    """
    text, dates = _dates(display_text(text))
    text = re.sub(r'((?:19|20)\d{2})\s*(?:财年|財年)', r' FY\1 ', text)
    text = re.sub(r'((?:19|20)\d{2})年?\s*(上半年|下半年)',
                  lambda m: ' '+('6M' if m[2] == '上半年' else 'H2') + m[1]+' ', text)
    text = re.sub(r'(?i)\b(?:H1|1H)\s*((?:19|20)\d{2})\b', r'6M\1', text)
    text = re.sub(r'(?i)\b2H\s*((?:19|20)\d{2})\b', r'H2\1', text)
    periods = []
    def period(m):
        periods.append(m[0].upper().replace(' ', ''))
        return ' '
    text = re.sub(r'(?i)(?<![A-Za-z0-9_.])(?:FY|CY|H[12]|Q[1-4]|(?:1[0-2]|[1-9])M)\s*(?:19|20)\d{2}(?!\d)', period, text)
    # Bare duration labels ("FY and 6M") are not million quantities.
    # Currency-qualified "RMB 6M" retains its monetary meaning.
    def duration(m):
        before = text[max(0, m.start()-16):m.start()]
        currency = r'(?:RMB|USD|HKD|EUR|GBP|CNY|CNH|SGD|JPY|AUD|CAD|CHF|US\$|HK\$|人民币|美元|港元|欧元|[$€£¥￥])'
        if (re.search(r'(?i)' + currency + r'\s*[+\-−]?\s*$', before)
                or re.match(r'(?i)\s*' + currency, text[m.end():])):
            return m[0]
        periods.append(m[0].upper())
        return ' '
    text = re.sub(r'(?i)(?<![A-Za-z0-9_.])(?:1[0-2]|[1-9])M(?![A-Za-z0-9])', duration, text)
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    text = PresentationPlanValidator._canonicalize_money_signs(text)
    text = re.sub(r'([+\-−])\s*(RMB|CNY|USD|HKD|EUR|GBP|US\$|HK\$)\s*(?=\d)',
                  r'\2 \1', text, flags=re.I)
    text = re.sub(r'(?:下降|下跌|减少|降低)\s*(\d[\d,]*(?:\.\d+)?[%％])', r'-\1', text)
    text = re.sub(r'([+\-−])\s+(?=\d)', lambda m: m[1].replace('−','-'), text)
    text = text.replace('％','%').replace('−','-')
    number = r'(?<![\d.])(?:\([-+]?\d[\d,]*(?:\.\d+)?%?\)|[-+]?\d[\d,]*(?:\.\d+)?%?)'
    numbers = Counter(n.lstrip('+') for n in re.findall(number, text))
    aliases = {'人民币':'rmb','CNY':'rmb','US$':'usd','HK$':'hkd','美元':'usd','港元':'hkd','欧元':'eur',
               '百万元':'million','百万':'million','千元':'thousand','千':'thousand',
               '十亿元':'billion','十亿':'billion','万亿元':'trillion','万亿':'trillion',
               '个百分点':'pp','基点':'bps'}
    text = re.sub('|'.join(sorted(map(re.escape, aliases),key=len,reverse=True)),lambda m: ' '+aliases[m[0]]+' ',text)
    units = Counter(m.casefold().removesuffix('s') for m in re.findall(
        r'(?<![A-Za-z])(?:RMB|USD|HKD|EUR|GBP|millions?|billions?|trillions?|thousands?|bps|pp)(?![A-Za-z])',text,re.I))
    for m in re.finditer(r'(?i)(?:RMB|USD|HKD|EUR|GBP)\s*[+\-]?\s*\d[\d,.]*\s*(m|k|b|mn|bn)\b',text):
        units[{'m':'million','mn':'million','k':'thousand','b':'billion','bn':'billion'}[m[1].casefold()]] += 1
    from .executive_brief import _quantities
    from .brief_table_evidence import canonical_quantity
    quantity_text = re.sub(r'(?i)\b(million|billion|trillion|thousand)s\b',r'\1',text)
    quantity_text = re.sub(r'(?i)([+\-]?\d[\d,.]*)\s+(RMB|USD|HKD|EUR|GBP)\s+(million|billion|trillion|thousand)\b',
                           r'\2 \1 \3',quantity_text)
    quantities = frozenset(canonical_quantity(c,v,u) for c,v,u in _quantities(quantity_text) if c or u)
    return dates, Counter(periods), numbers, units, text.count('*'), quantities
