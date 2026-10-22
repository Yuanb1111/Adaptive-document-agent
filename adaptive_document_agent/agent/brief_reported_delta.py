"""Validate a literal source-reported change without inventing endpoint levels."""
import re
from decimal import Decimal, InvalidOperation

from adaptive_document_agent.services.brief_table_evidence import canonical_quantity
from adaptive_document_agent.services.executive_brief import _MONEY_QUANTITY, _quantities
from adaptive_document_agent.services.source_quotes import continuous_quote_passages, normalize_quote

_CHANGE = r'(?:increases?|decreases?|changes?|reductions?|growth|declines?)'
_CHANGE_VERB = (r'(?:increas(?:e|ed|es|ing)|decreas(?:e|ed|es|ing)|rose|ris(?:e|es|ing)|'
                r'fell|fall(?:s|en|ing)?|grew|grow(?:s|n|ing)?|declin(?:e|ed|es|ing)|'
                r'reduc(?:e|ed|es|ing)|shrank|shrunk|shrink(?:s|ing)?|widen(?:ed|s|ing)?|'
                r'narrow(?:ed|s|ing)?|expand(?:ed|s|ing)?|contract(?:ed|s|ing)?|'
                r'climb(?:ed|s|ing)?|drop(?:ped|s|ping)?)')
_ADVERB = r'(?:[A-Za-z-]+ly|further|slightly|substantially|year-on-year|year\s+on\s+year)'
_OTHER_PREDICATE = re.compile(r'\b(?:is|are|was|were|be|been|being|has|have|had|will|would|'
    r'can|could|shall|should|may|might|did|does|do|acquired|purchased|bought|paid|sold|'
    r'obtained|financed|funded|issued|received|settled|valued)\b', re.I)
_RATE = re.compile(r'(?<![\w.])[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*'
                   r'(?:percentage\s+points?|percent\s+points?|basis\s+points?|bps\b|%|％|percent\b)', re.I)
_PERCENT = re.compile(r'(?<![\w.])[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:%|％|percent\b)', re.I)


def _by_predicate(before):
    """A direct change predicate, or its explicit parallel noun-phrase continuation.

    A reviewer must bind the full shared-predicate claim, never a detached noun
    phrase. A new finite/non-change predicate cannot inherit an earlier change.
    """
    if re.search(r'\b' + _CHANGE_VERB + r'(?:\s+' + _ADVERB + r')*\s+by\s*$', before, re.I):
        return True
    # Parallel claims may state the predicate once: X increased by A and Y by B.
    # The earlier amount is literal and must itself have a valid BY predicate.
    previous = [*list(_MONEY_QUANTITY.finditer(before)), *list(_RATE.finditer(before))]
    from adaptive_document_agent.extraction.borderless_table_extractor import _VALUE
    previous += [match for match in _VALUE.finditer(before)
                 if not any(part.start() <= match.start() < part.end() for part in previous)]
    for amount in sorted(previous, key=lambda match: match.end(), reverse=True):
        tail = before[amount.end():]
        shared = re.fullmatch(r'\s*,?\s*(?:and|or)\s+(.+?)\s+by\s*', tail, re.I)
        if (shared and not re.search(r'[;.!?\n]', shared[1])
                and not _OTHER_PREDICATE.search(shared[1]) and _by_predicate(before[:amount.start()])):
            return True
    return False


def _quantity(value):
    if _PERCENT.fullmatch(value.strip()):
        coefficient = re.sub(r'(?:%|％|percent)\s*$', '', value.strip(), flags=re.I)
        number = Decimal(coefficient.replace(',', '').replace('−', '-').strip())
        if not number.is_finite():
            raise InvalidOperation
        return '', format(number, 'f'), '%'
    if _MONEY_QUANTITY.fullmatch(value.strip()):
        return canonical_quantity(*next(iter(_quantities(value))))
    raw = value.strip().replace(',', '')
    if re.fullmatch(r'\(\s*\d+(?:\.\d+)?\s*\)', raw):
        raw = '-' + raw[1:-1].strip()
    number = Decimal(raw)
    if not number.is_finite():
        raise InvalidOperation
    return '', format(number, 'f'), ''


def _of_predicate(before):
    # The OF amount must belong to its own change noun, not an earlier sentence
    # or a different finite clause ending in a balance/valuation description.
    for change in re.finditer(r'\b' + _CHANGE + r'\b', before, re.I):
        match = re.fullmatch(r'\s*(?:in\s+([^.;!?\n]+?))?\s+of\s*', before[change.end():], re.I)
        if match and (not match[1] or not _OTHER_PREDICATE.search(match[1])):
            return True
    return False


def _reported_delta(text, expected):
    """Require the exact amount in an explicit BY/OF-change grammatical slot.

    This locates literal syntax, never chooses the source metric or its meaning.
    A level introduced by TO/FROM cannot masquerade as a reported change.
    """
    from adaptive_document_agent.extraction.borderless_table_extractor import _VALUE
    typed = [*list(_MONEY_QUANTITY.finditer(text)), *list(_RATE.finditer(text))]
    matches = typed + [match for match in _VALUE.finditer(text)
                       if not any(part.start() <= match.start() < part.end() for part in typed)]
    for match in matches:
        try:
            actual = _quantity(match[0])
        except (InvalidOperation, ValueError):
            continue
        # A bare coefficient cannot strip a monetary literal's currency/scale.
        # Both audience and source must match the SAME complete canonical tuple.
        if ((actual[0], actual[2]) != (expected[0], expected[2])
                or Decimal(actual[1]) != Decimal(expected[1])):
            continue
        before, after = text[:match.start()], text[match.end():]
        if (_by_predicate(before)
                or _of_predicate(before)
                or re.match(r'\s*' + _CHANGE + r'\b', after, re.I)
                or re.search(r'(?:增加|减少|上升|下降|变动)(?:了|为)?\s*$', before)):
            return True
    return False


def reported_delta_errors(comparison, item, *, pages=None):
    errors = []
    if not any(comparison.claim in text for text in (item.label, item.text)):
        errors.append('Comparison does not bind an exact audience claim')
    if (comparison.start_value or comparison.end_value or comparison.start_ref or comparison.end_ref
            or comparison.start_context or comparison.end_context or comparison.absolute_magnitude):
        errors.append('A reported change must not invent endpoint levels or absolute endpoint arithmetic')
    passages = continuous_quote_passages(item.evidence, pages) if pages is not None else item.evidence
    context, quote = comparison.delta_context, comparison.delta_quote
    if (not context or not any(normalize_quote(context) in normalize_quote(part.text) for part in passages)
            or not quote or normalize_quote(quote) not in normalize_quote(context)):
        errors.append('Reported change lacks its exact literal source phrase')
    try:
        quantity = _quantity(comparison.delta_value)
        if not _reported_delta(comparison.claim, quantity) or not _reported_delta(quote, quantity):
            errors.append('Reported change amount is not an exact native BY/OF-change in both audience and source')
        if Decimal(quantity[1]) == 0 and comparison.direction != 'equal':
            errors.append('A zero reported change cannot assert an increase or decrease')
    except (InvalidOperation, ValueError):
        errors.append('Reported change must be one exact finite source coefficient, monetary quantity or literal percentage')
    if comparison.source_direction is None or comparison.direction != comparison.source_direction:
        errors.append('Reported change direction contradicts its independently extracted literal source direction')
    if comparison.measure_basis != 'flow_total':
        errors.append('A reported change cannot substitute for a source-percentage endpoint comparison')
    if comparison.start_duration_months != comparison.end_duration_months:
        errors.append('Trend comparison mixes different reporting durations')
    return errors
