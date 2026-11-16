"""Lossless monetary display hints; never approve or rewrite model copy."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from .financial_formatter import split_unit_basis

if TYPE_CHECKING:
    from adaptive_document_agent.models import Observation


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


def calculated_amount_literal(value: float,observation: Observation) -> str | None:
    """Spell a Python delta in an input's supported display scale without changing it."""
    if not observation.unit_scale:
        return None
    try:
        amount=Decimal(str(value))/Decimal(str(observation.unit_scale))
        if not amount.is_finite():return None
        number=format(amount,',f')
        if '.' in number:number=number.rstrip('0').rstrip('.')
        candidate=observation.model_copy(update={'value':value,'raw_value':number})
        literal=source_amount_literal(candidate)
    except (InvalidOperation,TypeError,ValueError):
        return None
    return literal+(' units' if observation.unit_scale==1 else '') if literal else None
