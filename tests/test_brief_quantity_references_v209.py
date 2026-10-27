"""Reference transport preserves exact signed source amounts without semantic approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_quantity_references import quantity_patch_fields, expand_quantity_patch
from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from tests.test_executive_brief import gateway, result_for


def test_reference_patch_restores_native_amount_through_existing_source_gates():
    source = 'Revenue was USD 12 million in 2025.'
    original = dict(title='Results', items=[dict(label='Revenue', text='Revenue was USD 99 million in 2025.',
                    evidence=[dict(ref='p1_b1')])])
    patch = dict(item_0=dict(label='Revenue', text=['Revenue was ', dict(quantity_ref='q0'), ' in 2025.'],
                            evidence=[dict(ref='p1_b1')], quantity_representations=[]))
    g, client = gateway([original, patch])
    result = result_for([source])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert brief.items[0].text == 'Revenue was US$ 12 million in 2025.'
    assert len(client.editorial_calls) == 2
    audit = json.loads(next(w.message for w in result.validation_warnings if w.code == 'executive_brief_repair_audit'))
    assert audit['outcome'] == 'repaired'
    assert audit['source_quantity_reference_options']['item_0'] == {'q0': 'US$ 12 million'}


def test_exact_negative_sign_scale_and_denominator_are_not_recomputed():
    fields, catalogs = quantity_patch_fields({'item_0': (object, ...)}, {'item_0': [
        dict(amount_text='RMB -59883 thousand', literal_basis=['unit'])]},
        {'item_0': ['amount changes a source currency or magnitude']})
    before = deepcopy(catalogs)
    values = dict(item_0=dict(text=['Reported loss was ', dict(quantity_ref='q0'), '.']))
    assert expand_quantity_patch(values, catalogs)['item_0']['text'] == 'Reported loss was RMB -59883 thousand per unit.'
    assert isinstance(values['item_0']['text'], list) and catalogs == before


@pytest.mark.parametrize('parts', [
    [dict(quantity_ref='q99')], [dict(quantity_ref=None)], [dict(quantity_ref='q0', extra=True)],
    ['USD ', '99 million'], [], [dict(quantity_ref=['q0'])],
])
def test_unknown_references_and_literal_money_cannot_gain_trust(parts):
    with pytest.raises((ValueError, TypeError)):
        expand_quantity_patch(dict(item_0=dict(text=parts)), {'item_0': {'q0': 'USD 12 million'}})


def test_ambiguous_basis_and_unrelated_errors_do_not_create_an_invented_amount_option():
    fields = {'item_0': (object, ...)}
    assert quantity_patch_fields(fields, {'item_0': [dict(amount_text='USD 12 million', literal_basis=['hour', 'day'])]},
        {'item_0': ['unsupported numeric claims']}) == (fields, {})
    assert quantity_patch_fields(fields, {'item_0': [dict(amount_text='USD 12 million', literal_basis=[''])]},
        {'item_0': ['Meaning review: unsupported attribution']}) == (fields, {})


def test_reference_path_cannot_retain_obsolete_positive_annotations():
    with pytest.raises(ValueError, match='positive-magnitude'):
        expand_quantity_patch(dict(item_0=dict(text=[dict(quantity_ref='q0')],
            quantity_representations=[dict(quantity_text='USD 12 million')])),
            {'item_0': {'q0': 'USD -12 million'}})


def test_legacy_literal_transport_is_unchanged_and_still_rejected_for_wrong_amount():
    value = dict(item_0=dict(text='Revenue was USD 99 million.'))
    assert expand_quantity_patch(value, {'item_0': {'q0': 'USD 12 million'}}) == value
    source = 'Revenue was USD 12 million in 2025.'
    item = dict(label='Revenue', text=value['item_0']['text'], evidence=[dict(ref='p1_b1')])
    g, _ = gateway([dict(title='Results', items=[item]), dict(item_0=item)])
    with pytest.raises(ValueError, match='Executive brief failed'):
        ExecutiveBriefWriter(g).generate(result_for([source]))
