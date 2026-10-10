"""Give the bounded editorial repair exact source-native monetary options."""

from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from adaptive_document_agent.services.brief_table_evidence import canonical_quantity, quoted_table_context
from adaptive_document_agent.services.executive_brief import _quantities, normalized
from adaptive_document_agent.services.source_quotes import continuous_quote_passages
from .brief_quote_bounds import bounded_quote_item


def native_quantity_options(original, invalid, result, excerpts):
    """No conversions or guessed bindings: options come from literal item quotes.

    Python supplies spelling/scale/sign, while the model chooses which values
    belong in its finding and writes the prose. The normal source validator
    checks the returned patch independently.
    """
    options = {}
    for index in invalid:
        try:
            item = ExecutiveBriefItem.model_validate(bounded_quote_item(original['items'][index], excerpts))
        except ValueError:
            continue
        if any(normalized(q.text) not in normalized(excerpts.get(q.page, '')) for q in item.evidence):
            continue
        context = quoted_table_context(item, result, excerpts=excerpts)
        quantities = set(context.quantities)
        for passage in continuous_quote_passages(item.evidence, excerpts):
            quantities.update(canonical_quantity(*q) for q in _quantities(passage.text))
        options[f'item_{index}'] = [
            {'currency': c, 'signed_coefficient': v, 'source_scale': u,
             'literal_basis': sorted(context.bases.get((c, v, u), {''})),
             'amount_text': f'{c.upper()} {v} {u}',
             **({'magnitude_option': {'amount_text': f'{c.upper()} {v[1:]} {u}',
                    'quantity_representation': {'quantity_text': f'{c.upper()} {v[1:]} {u}',
                        'source_value': v, 'representation': 'absolute_magnitude'}}} if v.startswith('-') else {})}
            for c, v, u in sorted(quantities) if c and u in {'thousand', 'million', 'billion', 'trillion'}
        ]
    return options
