"""Only explicit model choices may remove obsolete positive-magnitude metadata."""
import pytest

from adaptive_document_agent.agent.brief_source_repair import correct_residual_source_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, BriefQuantityRepresentation
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import payload, result_for


def stale_binding():
    source = 'Net loss was USD -7 million in 2024.'
    result = result_for([source])
    original = ExecutiveBrief.model_validate(payload('Net loss was USD 99 million in 2024.'))
    original.items[0].evidence[0].text = source
    original.items[0].quantity_representations = [BriefQuantityRepresentation(
        quantity_text='USD 7 million', source_value='-7', representation='absolute_magnitude')]
    initial = {'item_0': validate_executive_brief(original, result, excerpts={1: source})}
    current = original.model_copy(deep=True)
    current.items[0].text = source
    return result, current, initial


def repair(result, brief, initial, response, *, audit=None):
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            assert self.calls == 1
            assert 'Existing quantity annotations cannot be added or rebound' in messages[0]['content']
            return schema(item_0=response)
    return correct_residual_source_errors(Client(), brief, result=result,
        excerpts={1: result.document.pages[0].text}, initial_errors=initial,
        audit={} if audit is None else audit)


def test_model_can_remove_existing_unused_annotation_after_selecting_same_signed_native_amount():
    result, brief, initial = stale_binding()
    before = brief.model_dump_json()
    audit = {}
    corrected = repair(result, brief, initial, {'text': brief.items[0].text,
        'remove_quantity_representation_indices': [0]}, audit=audit)
    assert corrected and not corrected.items[0].quantity_representations
    assert corrected.items[0].text == brief.items[0].text
    assert corrected.items[0].evidence == brief.items[0].evidence
    assert not validate_executive_brief(corrected, result)
    assert brief.model_dump_json() == before
    assert audit['residual_source_correction']['proposal']['item_0']['remove_quantity_representation_indices'] == [0]


@pytest.mark.parametrize('indices', [[1], [-1], [0, 0]])
def test_invented_negative_and_duplicate_removal_indices_fail(indices):
    result, brief, initial = stale_binding()
    assert repair(result, brief, initial, {'text': brief.items[0].text,
        'remove_quantity_representation_indices': indices}) is None


@pytest.mark.parametrize('indices', [[False], ['0']])
def test_removal_indices_do_not_coerce_boolean_or_string_addresses(indices):
    result, brief, initial = stale_binding()
    with pytest.raises(ValueError):
        repair(result, brief, initial, {'text': brief.items[0].text,
            'remove_quantity_representation_indices': indices})


@pytest.mark.parametrize('text', ['Net loss was USD 7 million in 2024.',
    'Net loss was EUR -7 million in 2024.', 'Net loss was USD -7 thousand in 2024.',
    'Net loss was USD -8 million in 2024.', 'Net loss was reported in 2024.'])
def test_removal_cannot_strip_a_needed_binding_or_change_delete_its_exact_signed_quantity(text):
    result, brief, initial = stale_binding()
    assert repair(result, brief, initial, {'text': text,
        'remove_quantity_representation_indices': [0]}) is None


def test_signed_copy_does_not_trigger_automatic_metadata_cleanup_without_model_selection():
    result, brief, initial = stale_binding()
    assert repair(result, brief, initial, {'text': brief.items[0].text}) is None


def test_residual_patch_cannot_add_or_rebind_annotations():
    result, brief, initial = stale_binding()
    with pytest.raises(ValueError):
        repair(result, brief, initial, {'text': brief.items[0].text,
            'quantity_representations': []})


@pytest.mark.parametrize(('source_value', 'coefficient'), [
    ('-7,0', '7'), ('-7.0', '7'), ('-1,000', '1000'), ("-1'000", '1000'),
    ('-1 000', '1000'), ('-1\u00a0000', '1000'), ('-1\u202f000', '1000'), ('-1\u2019000', '1000'),
])
def test_removal_uses_existing_magnitude_contract_numeric_normalization(source_value, coefficient):
    result, brief, _ = stale_binding()
    source = f'Net loss was USD -{coefficient} million in 2024.'
    result.document.pages[0].text = source
    item = brief.items[0]
    item.text = source
    item.evidence[0].text = source
    item.quantity_representations[0].quantity_text = f'USD {coefficient} million'
    item.quantity_representations[0].source_value = source_value
    positive = brief.model_copy(deep=True)
    positive.items[0].text = source.replace(f'-{coefficient}', coefficient)
    # These spellings are already valid in the ordinary magnitude contract.
    assert not validate_executive_brief(positive, result)
    original = brief.model_copy(deep=True)
    original.items[0].text = 'Net loss was USD 99 million in 2024.'
    initial = {'item_0': validate_executive_brief(original, result)}
    corrected = repair(result, brief, initial, {'text': source,
        'remove_quantity_representation_indices': [0]})
    assert corrected and not corrected.items[0].quantity_representations
    assert not validate_executive_brief(corrected, result)


@pytest.mark.parametrize('unsupported', ['(7)', '\u22127'])
def test_removal_does_not_silently_add_source_value_syntax_rejected_by_existing_contract(unsupported):
    result, brief, initial = stale_binding()
    brief.items[0].quantity_representations[0].source_value = unsupported
    assert repair(result, brief, initial, {'text': brief.items[0].text,
        'remove_quantity_representation_indices': [0]}) is None


@pytest.mark.parametrize('accepted', [True, False])
def test_residual_metadata_change_still_requires_fresh_independent_meaning_verdict(accepted):
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    result, brief, _ = stale_binding()
    original = brief.model_copy(deep=True)
    original.items[0].text = 'Net loss was USD 99 million in 2024.'
    reviewed = []
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return original
            if self.calls == 2:
                return schema(item_0=brief.items[0].model_dump())
            if self.calls == 3:
                return schema(item_0=dict(text=brief.items[0].text,
                    remove_quantity_representation_indices=[0]))
            assert self.calls == 4 and not accepted
            # The existing final meaning-patch opportunity cannot change an
            # independent rejection into approval merely by echoing the text.
            return schema(item_0=dict(text=brief.items[0].text))
    def review(value):
        reviewed.append(value.model_dump(mode='json'))
        return {} if accepted else {0: ['Independent meaning rejection remains unresolved.']}
    client = Client()
    args = dict(result=result, excerpts={1: result.document.pages[0].text}, topics=[],
                source_context={}, semantic_validator=review)
    if accepted:
        final = generate_with_item_repair(client, [{'role': 'system', 'content': 'Use source evidence.'}], **args)
        assert not final.items[0].quantity_representations
    else:
        with pytest.raises(ValueError, match='Independent meaning rejection'):
            generate_with_item_repair(client, [{'role': 'system', 'content': 'Use source evidence.'}], **args)
    assert client.calls == (3 if accepted else 4) and reviewed
    assert all(not value['items'][0]['quantity_representations'] for value in reviewed)
