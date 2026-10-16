"""Keep a meaning-only correction inside its displayed quantities and source periods."""
from adaptive_document_agent.services.executive_brief import _quantities
from adaptive_document_agent.services.brief_table_evidence import canonical_quantity, quoted_table_context
from .brief_audit_scope import audit_status_errors, audit_status_options, misplaced_parenthetical_statuses
from .brief_period_clarification import original_period_identities, quantity_text_with_bound_dates


def check_meaning_contract(original, candidate, indices, *, result, excerpts, inventories, periods):
    """Return exact violations and whether one narrow protocol correction is possible.

    A quoted but newly enumerated table cell remains forbidden. Its presence in
    the source permits feedback asking the model to remove it, never acceptance.
    Invented quantities and ungrounded audit assertions do not get this retry.
    """
    errors, feedback, recoverable = [], {}, True
    items = list(candidate.items)
    for index in indices:
        before, item = original.items[index], items[index]
        raw_shown = {canonical_quantity(*q) for q in _quantities(item.text)}
        aliases = original_period_identities(before, inventories[index], result=result)
        checked_text = quantity_text_with_bound_dates(item.text, periods[index], inventories[index],
                                                     original_periods=aliases)
        shown = {canonical_quantity(*q) for q in _quantities(checked_text)}
        original_text = quantity_text_with_bound_dates(before.text, periods[index], inventories[index],
                                                       original_periods=aliases)
        permitted = {canonical_quantity(*q) for q in _quantities(original_text)}
        representations = []
        for representation in before.quantity_representations:
            positive = {canonical_quantity(*q) for q in _quantities(representation.quantity_text)}
            permitted.update((c, representation.source_value, u) for c, _, u in positive)
            if positive and positive <= raw_shown:
                representations.append(representation)
        items[index] = item.model_copy(update={'quantity_representations': representations})
        introduced = shown - permitted
        item_errors = []
        if introduced:
            item_errors.append(f'item_{index}: meaning correction introduced new quantities: {sorted(introduced)}')
            context = quoted_table_context(before, result, excerpts=excerpts)
            quoted = set(context.quantities) | {('', value, '%') for value in context.percentages}
            quoted.update(canonical_quantity(*q) for quote in before.evidence for q in _quantities(quote.text))
            recoverable &= all((currency or unit) and quantity in quoted
                               for quantity in introduced for currency, _, unit in [quantity])
        statuses = audit_status_errors(item, result, inventory=inventories[index])
        placements = misplaced_parenthetical_statuses(item, result, inventory=inventories[index])
        if statuses:
            item_errors.extend(statuses)
            recoverable &= all(any(f"'{row['status']}'" in error
                                   and f"'{row['ambiguous_preceding_period']}'" in error
                                   for row in placements) for error in statuses)
        if item_errors:
            errors.extend(item_errors)
            feedback[f'item_{index}'] = {'errors': item_errors,
                'permitted_quantities': sorted(permitted),
                'new_table_quantities_to_remove': sorted(introduced),
                'period_clarifications': periods[index],
                'source_status_options': audit_status_options(item, result, inventory=inventories[index]),
                'misplaced_statuses': placements}
    return candidate.model_copy(update={'items': items}), errors, feedback, bool(errors) and recoverable
