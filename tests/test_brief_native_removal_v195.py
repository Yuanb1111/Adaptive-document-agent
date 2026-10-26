"""An invalid rounded annotation cannot block explicit repair to exact native copy."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.brief_source_repair import correct_residual_source_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote, BriefQuantityRepresentation
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for


def case():
    source = 'Net loss was RMB -51687 thousand in 2023. Revenue was RMB 20 million in 2023.'
    result = result_for([source])
    current = ExecutiveBrief(items=[ExecutiveBriefItem(label='Loss', text='Net loss was RMB 51.7 million in 2023.',
        evidence=[BriefQuote(page=1, text=source)], quantity_representations=[BriefQuantityRepresentation(
            quantity_text='RMB 51.7 million', source_value='-51687', representation='absolute_magnitude')]),
        ExecutiveBriefItem(label='Revenue', text='Revenue was RMB 20 million in 2023.',
            evidence=[BriefQuote(page=1, text=source)])])
    initial = {'item_0': validate_executive_brief(ExecutiveBrief(items=[current.items[0]]), result),
               'item_1': ['Revenue: unsupported numeric claims [99].']}
    return result, current, initial


def correct(result, brief, initial, text, indices=(0,)):
    audit = {}
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            assert set(schema.model_fields) == {'item_0'}
            return schema(item_0=dict(text=text, remove_quantity_representation_indices=list(indices)))
    output = correct_residual_source_errors(Gateway(), brief, result=result,
        excerpts={1: result.document.pages[0].text}, initial_errors=initial, audit=audit)
    return output, audit


def test_explicit_native_repair_removes_mixed_scale_metadata_and_preserves_raw_evidence():
    result, brief, initial = case()
    original = deepcopy((result.document, brief))
    output, audit = correct(result, brief, initial, 'Net loss was RMB -51687 thousand in 2023.')
    assert output and not output.items[0].quantity_representations
    assert not validate_executive_brief(output, result)
    assert output.items[0].evidence == brief.items[0].evidence
    assert output.items[1] == brief.items[1]
    assert (result.document, brief) == original
    assert audit['residual_source_correction']['semantic_approval'] is False


@pytest.mark.parametrize('text', ['Net loss was RMB 51687 thousand in 2023.',
    'Net loss was RMB -51.7 million in 2023.', 'Net loss was RMB -51688 thousand in 2023.',
    'Net loss was USD -51687 thousand in 2023.', 'Net loss was RMB -51687 million in 2023.',
    'Net loss was reported in 2023.', 'Net loss was RMB 51.7 million; also RMB -51687 thousand in 2023.'])
def test_removal_does_not_authorize_rounding_sign_currency_unit_changes_or_deletion(text):
    result, brief, initial = case()
    output, _ = correct(result, brief, initial, text)
    assert output is None


def test_no_implicit_cleanup_without_model_removal_choice():
    result, brief, initial = case()
    output, _ = correct(result, brief, initial, 'Net loss was RMB -51687 thousand in 2023.', indices=())
    assert output is None


def test_ambiguous_native_scale_cannot_be_inferred_from_invalid_old_annotation():
    result, brief, initial = case()
    source = result.document.pages[0].text + ' Another measure was RMB -51687 billion.'
    result.document.pages[0].text = source
    brief.items[0].evidence[0].text = source
    output, _ = correct(result, brief, initial, 'Net loss was RMB -51687 thousand in 2023.')
    assert output is None


def test_another_source_coefficient_cannot_be_substituted_when_removing_metadata():
    result, brief, initial = case()
    brief.items[0].quantity_representations[0].source_value = '-59900'
    output, _ = correct(result, brief, initial, 'Net loss was RMB -51687 thousand in 2023.')
    assert output is None


@pytest.mark.parametrize('numeric_flag,hidden_heading,passes', [
    (False, False, True), (True, False, False), (False, True, False),
])
def test_comparison_flag_correction_requires_fresh_independent_audience_review(numeric_flag, hidden_heading, passes):
    from tests.test_brief_direction_repair_v174 import loss_fixture, ScriptedGateway
    from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
    brief, result, original, initial, _, _ = loss_fixture()
    if not hidden_heading:
        brief.items[0].label = 'Reported results'
        initial['items'][0]['omitted_directional_claims'] = []
    corrected = dict(items=[dict(index=0, accepted=True, reason='Dated facts verified.',
        numeric_comparison=numeric_flag, comparisons=[])])
    final = dict(items=[dict(index=0, comparisons=[],
        omitted_directional_claims=['Losses widen', 'revenue grows'] if hidden_heading else [])])
    gateway = ScriptedGateway([original, initial, corrected, final])
    errors = meaning_validator(gateway, result=result)(brief)
    assert (not errors) is passes
    assert len(gateway.calls) == (3 if numeric_flag else 4)
    assert 'numeric_comparison=false with comparisons=[]' in gateway.calls[2][0][-1]['content']
