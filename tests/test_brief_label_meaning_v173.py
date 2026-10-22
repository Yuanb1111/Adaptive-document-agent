"""Displayed brief labels retain the same source and arithmetic obligations as bodies."""
import pytest

from adaptive_document_agent.agent.brief_meaning_review import (
    MeaningComparison, comparison_errors, meaning_validator,
)
from adaptive_document_agent.models.executive_brief import (
    BriefQuote, ExecutiveBrief, ExecutiveBriefItem,
)
from tests.test_executive_brief import result_for


def loss_item(label='Adjusted loss widens on a non-IFRS basis'):
    source = ('Adjusted loss on a non-IFRS basis was (39.898) in FY2022 and '
              '(81.817) in FY2023 (RMB million).')
    return ExecutiveBriefItem(label=label,
        text='Adjusted loss widened from RMB39.898 million in FY2022 to RMB81.817 million in FY2023.',
        evidence=[BriefQuote(page=1, text=source)])


def loss_comparison(item, *, direction='increase', claim=None):
    return MeaningComparison(claim=item.label if claim is None else claim,
        start_value='(39.898)', end_value='(81.817)', direction=direction,
        absolute_magnitude=True, start_context=item.evidence[0].text,
        end_context=item.evidence[0].text, start_duration_months=12, end_duration_months=12)


@pytest.mark.parametrize(('label', 'direction', 'valid'), [
    ('Adjusted loss narrows on a non-IFRS basis', 'decrease', False),
    ('Adjusted loss widens on a non-IFRS basis', 'increase', True),
])
def test_label_direction_uses_bound_endpoint_arithmetic_even_when_body_is_correct(label, direction, valid):
    item = loss_item(label)
    errors = comparison_errors(loss_comparison(item, direction=direction), item)
    assert not any('exact audience claim' in error for error in errors)
    if valid:
        assert errors == []
    else:
        assert any('direction contradicts' in error for error in errors)


@pytest.mark.parametrize('claim', [
    'Adjusted losses widen on a non-IFRS basis',  # A paraphrase is not exact.
    'basisAdjusted loss widened',  # Concatenating the fields cannot bind a claim.
    'basis. Adjusted loss widened',
])
def test_label_support_does_not_accept_unbound_or_cross_boundary_claims(claim):
    item = loss_item()
    assert any('exact audience claim' in error for error in
               comparison_errors(loss_comparison(item, claim=claim), item))


@pytest.mark.parametrize('wrong_label', [False, True])
def test_independent_review_checks_label_and_body_without_rebinding_a_valid_label(wrong_label):
    item = loss_item('Adjusted loss narrows on a non-IFRS basis' if wrong_label
                     else 'Adjusted loss widens on a non-IFRS basis')
    comparisons = [loss_comparison(item, direction='decrease' if wrong_label else 'increase'),
                   loss_comparison(item, claim=item.text)]

    class Gateway:
        def __init__(self):
            self.calls = []

        def generate_structured(self, messages, schema, **kwargs):
            self.calls.append(messages)
            assert len(self.calls) == 1, 'An exact label claim must not require binding correction.'
            return schema.model_validate({'items': [dict(index=0, accepted=True,
                reason='The reviewer has supplied the claimed directions and literal endpoints.',
                numeric_comparison=True,
                comparisons=[comparison.model_dump(mode='json') for comparison in comparisons])]})

    gateway = Gateway()
    errors = meaning_validator(gateway, result=result_for([item.evidence[0].text]))(
        ExecutiveBrief(items=[item]))
    if wrong_label:
        assert any('direction contradicts' in error for error in errors[0])
    else:
        assert errors == {}
    prompt = gateway.calls[0][0]['content']
    assert 'Review item.label and item.text independently and together' in prompt
    assert 'numeric values appear only in the body' in prompt
    assert 'never a concatenation across their boundary' in prompt


def reported_change_item():
    source = 'Deposits increased by USD12 million in FY2024.'
    item = ExecutiveBriefItem(label='Deposits increased by USD12 million',
        text='The reported increase in FY2024 was USD12 million.',
        evidence=[BriefQuote(page=1, text=source)])
    comparison = MeaningComparison(claim=item.label, comparison_kind='reported_delta',
        direction='increase', delta_value='USD12 million', delta_context=source,
        delta_quote=source, source_direction='increase')
    return item, comparison


def test_label_reported_delta_keeps_native_amount_and_direction_checks():
    item, comparison = reported_change_item()
    assert comparison_errors(comparison, item) == []
    assert any('direction contradicts' in error for error in comparison_errors(
        comparison.model_copy(update={'direction': 'decrease'}), item))
    assert any('exact native BY/OF-change' in error for error in comparison_errors(
        comparison.model_copy(update={'delta_value': 'USD13 million'}), item))


@pytest.mark.parametrize('claim', ['Deposits rose by USD12 million',
                                  'millionThe reported increase',
                                  'million. The reported increase'])
def test_reported_delta_label_claim_must_be_exact_and_within_one_field(claim):
    item, comparison = reported_change_item()
    assert any('exact audience claim' in error for error in comparison_errors(
        comparison.model_copy(update={'claim': claim}), item))


def test_reported_delta_cannot_borrow_its_change_amount_from_body_for_a_numeric_free_label():
    item, comparison = reported_change_item()
    item.label = 'Deposits increased'
    assert any('exact native BY/OF-change' in error for error in comparison_errors(
        comparison.model_copy(update={'claim': item.label}), item))
