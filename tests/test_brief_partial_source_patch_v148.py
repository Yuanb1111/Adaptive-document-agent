"""One rejected residual patch cannot discard independently repaired findings."""

import json
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
from adaptive_document_agent.agent.brief_source_repair import correct_residual_source_errors
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from tests.test_executive_brief import result_for


SOURCE = ('Revenue was USD 12 million in 2024. Expenses were USD -7 million in 2024. '
          'Workers numbered 10 in 2024. Cash was USD 5 million in 2024.')


def _brief():
    texts = ['Revenue was USD 99 million in 2024.', 'Expenses were USD 9 million in 2024.',
             'Workers numbered 999 in 2024.', 'Cash was USD 5 million in 2024.']
    return ExecutiveBrief(items=[ExecutiveBriefItem(label=label, text=text,
        evidence=[BriefQuote(page=1, text=SOURCE)]) for label, text in
        zip(['Revenue', 'Expenses', 'Workers', 'Cash'], texts)])


def _native_patch(original):
    items = [item.model_copy(deep=True) for item in original.items]
    for item, text in zip(items, ['Revenue was USD 12 million in 2024.',
            'Expenses were USD 7 million in 2024.', 'Workers numbered 9 in 2024.']):
        item.text = text
    return original.model_copy(update={'items': items})


@pytest.mark.parametrize('bad_patch', [
    {'text': 'Expenses were USD 7 million in 2024.'},
    {'text': 'Expenses were USD -7 million in 2024.', 'remove_quantity_representation_indices': [99]},
    {'text': 'Expenses were USD -7 million in 2024.', 'evidence': []},
])
def test_source_valid_sibling_survives_bad_sign_metadata_or_unauthorized_field(bad_patch):
    original = _brief()
    current = _native_patch(original)
    before = current.model_dump(mode='json')
    result = result_for([SOURCE])
    errors = {f'item_{i}': validate_executive_brief(ExecutiveBrief(items=[item]), result)
              for i, item in enumerate(original.items) if i != 3}

    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            assert set(schema.model_fields) == {'item_1', 'item_2'}
            return SimpleNamespace(model_dump=lambda **kwargs: {
                'item_1': bad_patch, 'item_2': {'text': 'Workers numbered 10 in 2024.'}})

    audit = {}
    revised = correct_residual_source_errors(Gateway(), current, result=result, excerpts={1: SOURCE},
        initial_errors=errors, audit=audit)
    assert revised.items[2].text == 'Workers numbered 10 in 2024.'
    assert [revised.items[i] for i in [0, 1, 3]] == [current.items[i] for i in [0, 1, 3]]
    assert revised.items[2].evidence == current.items[2].evidence
    assert current.model_dump(mode='json') == before
    record = audit['residual_source_correction']
    assert record['status'] == 'partial_source' and record['accepted_indices'] == [2]
    assert set(record['rejected_items']) == {1} and record['semantic_approval'] is False
    assert validate_executive_brief(revised, result)  # Bad sibling has no approval.


@pytest.mark.parametrize('accept_changed_item', [True, False, 'after_correction'])
def test_partial_source_merge_still_obeys_each_fresh_meaning_verdict(accept_changed_item):
    original = _brief()
    current = _native_patch(original)
    result = result_for([SOURCE])
    reviews = []

    class Gateway:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return original
            if self.calls == 2:
                return schema(**{f'item_{i}': current.items[i].model_dump() for i in [0, 1, 2]})
            if self.calls == 3:
                return schema(item_1={'text': current.items[1].text},
                              item_2={'text': 'Workers numbered 10 in 2024.'})
            assert self.calls == 4 and accept_changed_item is not True
            assert set(schema.model_fields) == {'item_1'}  # Subset's own exact address.
            return schema(item_1={'text': 'Workers numbered 10 in 2024.' +
                (' As reported.' if accept_changed_item == 'after_correction' else '')})

    def meaning(brief):
        reviews.extend(item.model_dump(mode='json') for item in brief.items)
        return {i: ['The independent meaning review rejects this finding.']
                for i, item in enumerate(brief.items)
                if item.label == 'Workers' and accept_changed_item is not True
                and not (accept_changed_item == 'after_correction' and item.text.endswith(' As reported.'))}

    gateway = Gateway()
    final = generate_with_item_repair(gateway, [{'role': 'system', 'content': 'Use source evidence.'}],
                                     result=result, excerpts={1: SOURCE}, topics=[],
                                     source_context={}, semantic_validator=meaning)
    assert [item.label for item in final.items] == (['Revenue', 'Workers', 'Cash']
                                                   if accept_changed_item else ['Revenue', 'Cash'])
    assert not validate_executive_brief(final, result)
    assert any(item['label'] == 'Workers' and item['text'] == 'Workers numbered 10 in 2024.' for item in reviews)
    assert gateway.calls == (3 if accept_changed_item is True else 4)
    audit = json.loads(next(w.message for w in result.validation_warnings if w.code == 'executive_brief_repair_audit'))
    assert audit['meaning_source_indices'] == [0, 2, 3]
    assert audit['discarded_indices'] == ([1] if accept_changed_item else [1, 2])


def test_one_displayed_percentage_does_not_acquire_an_unwritten_comparison_endpoint():
    from adaptive_document_agent.agent.brief_meaning_review import MeaningComparison, comparison_errors
    item = ExecutiveBriefItem(label='Completion rate', text='The completion rate was higher at 47.3%.',
        evidence=[BriefQuote(page=1, text='Completion rate rose from 44.9% in 2023 to 47.3% in 2024.')])
    comparison = MeaningComparison(claim=item.text, start_value='44.9%', end_value='47.3%',
        direction='increase', measure_basis='source_percentage',
        start_context=item.evidence[0].text, end_context=item.evidence[0].text,
        start_duration_months=12, end_duration_months=12)
    assert any('both explicit claim percentages' in error for error in comparison_errors(comparison, item))
