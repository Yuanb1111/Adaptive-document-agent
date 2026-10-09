"""Exact monetary scale changes after source validation, shared by web and PPT."""

from decimal import Decimal
import re


_THOUSANDS = re.compile(
    r'(?<!\w)(?P<currency>RMB|CNY|CNH|USD|HKD|SGD|EUR|GBP|JPY|AUD|CAD|CHF|US\$|HK\$)\s*'
    r'(?P<amount>\(\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*\)|[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s+thousands?\b', re.I)


def readable_money(text):
    """Rescale explicit monetary phrases exactly; preserve rates and raw copy."""
    def replace(match):
        if re.match(r'\s*(?:/|per\b)', text[match.end():], re.I):
            return match[0]
        raw = match['amount'].replace(',', '').replace('−', '-').strip()
        accounting = raw.startswith('(')
        value = -Decimal(raw[1:-1].strip()) if accounting else Decimal(raw)
        if abs(value) < 1000:
            return match[0]
        amount = format(value / 1000, ',f').rstrip('0').rstrip('.') if value % 1000 else f'{value / 1000:,.0f}'
        if match['amount'].startswith('+'):
            amount = '+' + amount
        if accounting:
            amount = '(' + amount.lstrip('-') + ')'
        return f"{match['currency']} {amount} million"
    return _THOUSANDS.sub(replace, text)
