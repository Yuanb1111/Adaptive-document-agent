"""Lossless monetary display hints; never approve or rewrite model copy."""
import re
from decimal import Decimal, InvalidOperation

from .financial_formatter import split_unit_basis


def source_amount_literal(observation):
    """Spell a reported raw amount with its explicit typed currency and scale."""
    suffix = {1: '', 1000: ' thousand', 10**6: ' million', 10**9: ' billion'}
    if (not observation.currency or observation.value is None
            or observation.unit_family not in {'generic', 'currency'}
            or observation.unit not in {None, 'currency', observation.currency}
            or observation.unit_scale not in suffix
            or split_unit_basis(observation.raw_unit)[1]):
        return None
    raw = observation.raw_value.strip()
    accounting = raw.startswith('(') and raw.endswith(')')
    number = raw[1:-1].strip() if accounting else raw
    if not re.fullmatch(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', number):
        return None
    try:
        value = Decimal(number.replace(',', '')) * (-1 if accounting else 1)
        if value * Decimal(str(observation.unit_scale)) != Decimal(str(observation.value)):
            return None
    except InvalidOperation:
        return None
    text = f'{observation.currency} {number}{suffix[observation.unit_scale]}'
    return f'({text})' if accounting else text
