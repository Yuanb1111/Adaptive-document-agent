"""Validate explicit magnitude representations without changing raw signs."""
from decimal import Decimal, InvalidOperation


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
    replacements, errors = {}, []
    for binding in item.quantity_representations:
        phrase = binding.quantity_text
        values = _quantities(phrase)
        percent = bool(_QUANTITY.fullmatch(phrase) and phrase.endswith(('%','％')))
        if (phrase in replacements or text.count(phrase) != 1 or len(values) != 1
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
        replacements[phrase] = f'{signed}%' if percent else f'{currency} {signed} {unit}'
    for phrase, replacement in replacements.items():
        text = text.replace(phrase, replacement, 1)
    return text, errors
