"""Validate explicit magnitude representations without changing raw signs."""
from decimal import Decimal, InvalidOperation


def source_native_quantity_hint(currency, value, unit, quantities):
    """Offer one exact source candidate for repair; never authorize rounding."""
    scales = {'': 1, 'thousand': 1000, 'million': 1000000,
              'billion': 1000000000, 'trillion': 1000000000000}
    if not currency or unit not in scales:
        return None
    try:
        claim = Decimal(value)
        precision = Decimal(1).scaleb(claim.as_tuple().exponent)
        candidates = set()
        for c, v, u in quantities:
            if c != currency or u not in scales:
                continue
            converted = abs(Decimal(v)) * scales[u] / scales[unit]
            if converted.quantize(precision) == abs(claim):
                candidates.add((c, v, u))
        return next(iter(candidates)) if len(candidates) == 1 else None
    except InvalidOperation:
        return None


def magnitude_claim_text(item, context, quantities):
    """Return a validation-only signed view; display copy and sources stay intact.

    The model decides whether a phrase denotes magnitude. Python proves the
    exact absolute-value relationship in that item's own literal evidence.
    No rounding, currency conversion, rescaling or inferred semantic alias is
    permitted by this contract. Unannotated positive claims remain blocked.
    """
    from .executive_brief import _quantities, _MONEY_QUANTITY, _QUANTITY
    from .brief_table_evidence import canonical_quantity
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

    from adaptive_document_agent.models.executive_brief import brief_claim_text
    text = brief_claim_text(item, canonicalize_table_signs=True)
    text = PresentationPlanValidator._canonicalize_money_signs(text)
    replacements, errors, owned = [], [], set()
    for binding in item.quantity_representations:
        phrase = binding.quantity_text
        values = _quantities(phrase)
        percent = bool(_QUANTITY.fullmatch(phrase) and phrase.endswith(('%','％')))
        import re
        compact = lambda value: re.sub(r'\s+', '', value)
        matcher = _QUANTITY if percent else _MONEY_QUANTITY
        spans = [match.span() for match in matcher.finditer(text)
                 if compact(match[0]) == compact(phrase)]
        if (len(spans) != 1 or spans[0] in owned or len(values) != 1
                or not (_MONEY_QUANTITY.fullmatch(phrase) or percent)):
            errors.append('magnitude representation needs one unique displayed quantity')
            continue
        currency, value, unit = canonical_quantity(*next(iter(values)))
        try:
            source = Decimal(PresentationPlanValidator._normalize_number(binding.source_value))
            shown = Decimal(value)
        except InvalidOperation:
            errors.append('magnitude representation has an invalid source value')
            continue
        signed = PresentationPlanValidator._normalize_number(binding.source_value)
        supported = (currency, signed, unit) in quantities or (percent and signed in context.percentages)
        if ((not currency and not percent) or not unit or source >= 0 or shown != abs(source)
                or not supported):
            errors.append('magnitude representation does not match an exact signed source quantity')
            continue
        # Replace only this complete quantity, not equal digits in dates or
        # other metrics. Denominator/date checks still operate on the full copy.
        owned.add(spans[0])
        replacements.append((*spans[0], f'{signed}%' if percent else f'{currency} {signed} {unit}'))
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, errors
