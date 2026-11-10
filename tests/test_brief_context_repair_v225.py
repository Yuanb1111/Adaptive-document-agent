"""A missing declared scope and a changed final selection get bounded repairs."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from adaptive_document_agent.agent.brief_assurance_bindings import assurance_binding_errors
from adaptive_document_agent.agent.brief_item_repair import _salvage
from adaptive_document_agent.agent.brief_selection_repair import selection_context_repair
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem
from tests.test_brief_assurance_bindings import case
from tests.test_brief_item_repair import item
from tests.test_brief_targeted_contract_v147 import Replies
from tests.test_executive_brief import result_for


@pytest.mark.parametrize('missing', ['status', 'period', 'both'])
def test_declared_assurance_needs_its_own_literal_audience_scope(missing):
    _, value, inventory, _, binding = case()
    text = binding['claim']
    if missing in {'status', 'both'}:
        text = text.replace('unaudited ', '')
    if missing in {'period', 'both'}:
        text = text.replace('6M2023', 'that period')
    value.text = value.text.replace(binding['claim'], text)
    binding['claim'] = text
    errors, retryable = assurance_binding_errors(value, inventory, [binding])
    assert errors and retryable
    assert any('audience clause' in error for error in errors)


def test_scope_metadata_cannot_borrow_status_from_unknown_or_other_period():
    _, value, inventory, catalog, binding = case()
    assert assurance_binding_errors(value, inventory, [binding]) == ([], False)
    unknown = next(ref for ref, row in catalog.items() if row['status'] == 'unknown')
    binding['source_refs'] = [unknown]
    errors, retryable = assurance_binding_errors(value, inventory, [binding])
    assert errors and not retryable


@pytest.mark.parametrize('outcome', ['accepted', 'rejected', 'new_quantity'])
def test_removed_companion_can_reopen_only_newly_rejected_selection_text(outcome):
    source = 'Cash was 4. Costs were 8. Revenue was 12.'
    result = result_for([source])
    values = [item('Cash was 4.', label='Cash'), item('Costs were 8.', label='Costs'),
              item('Revenue was 12.', label='Revenue')]
    original = deepcopy(values)
    corrected_text = 'Reported costs were 8.' if outcome != 'new_quantity' else 'Reported costs were 99.'
    gateway = Replies([{'item_0': {'text': corrected_text}}])
    reviews = []
    def review(brief):
        reviews.append(deepcopy(brief))
        if len(brief.items) == 3:
            return {0: ['Cash scope is unsupported.']}
        if outcome == 'accepted' and brief.items[0].text == corrected_text:
            return {}
        return {0: ['Clarify the cost basis after the companion is removed.']}
    audit = {}
    repair = selection_context_repair(gateway, result=result, excerpts={1: source}, topics=[],
        source_context={}, evidence_catalog=None, semantic_validator=review, audit=audit)
    final, removed = _salvage(values, {i: ExecutiveBriefItem.model_validate(values[i]) for i in (1, 2)},
        'Summary', result, {1: source}, [], review, audit, selection_repair=repair)
    assert (final is not None) == (outcome == 'accepted')
    if final:
        assert removed == [0]
        assert final.items[0].text == corrected_text
        assert final.items[0].evidence == ExecutiveBriefItem.model_validate(values[1]).evidence
        assert final.items[1] == ExecutiveBriefItem.model_validate(values[2])
        assert reviews[-1] == final
    assert len(gateway.calls) == 1 and gateway.calls[0][1] == {'item_0'}
    assert audit['selection_context_correction']['original_indices'] == [1, 2]
    assert values == original
    # No repeated correction or successive drop loop can be purchased.
    assert repair(ExecutiveBrief(items=[ExecutiveBriefItem.model_validate(v) for v in values[1:]]),
                  {0: ['Still rejected.']}, [1, 2]) is None
    assert len(gateway.calls) == 1


def test_unmodified_selection_does_not_reopen_a_failing_lock():
    source = 'Costs were 8. Revenue was 12.'
    result = result_for([source])
    values = [item('Costs were 8.'), item('Revenue was 12.')]
    calls = []
    final, _ = _salvage(values, {0: ExecutiveBriefItem.model_validate(values[0])}, 'Summary', result,
        {1: source}, [], lambda brief: {0: ['Unchanged failure.']}, {},
        selection_repair=lambda *args: calls.append(args))
    assert final is None and calls == []


def test_private_779_missing_scope_is_repaired_before_independent_review():
    location = os.environ.get('BRIEF_DIAGNOSTIC_779')
    if not location:
        pytest.skip('Private diagnostic is supplied only for local regression.')
    from adaptive_document_agent.models import PipelineResult
    from adaptive_document_agent.agent.brief_audit_scope import source_audit_scope
    from adaptive_document_agent.agent.brief_period_clarification import period_clarification_options
    from adaptive_document_agent.agent.brief_meaning_contract import check_meaning_contract
    result = PipelineResult.model_validate_json(Path(location).read_bytes())
    audit = json.loads(next(w.message for w in reversed(result.validation_warnings)
                           if w.code == 'executive_brief_repair_audit'))
    before = ExecutiveBrief.model_validate(audit['original'])
    for key, value in audit['patch'].items():
        if key.startswith('item_'):
            before.items[int(key[5:])] = ExecutiveBriefItem.model_validate(value)
    candidate = before.model_copy(deep=True)
    declarations = audit['post_source_meaning_correction']['proposal']
    bindings, inventories, periods = {}, {}, {}
    for key, value in declarations.items():
        i = int(key[5:])
        candidate.items[i].text = value['text']
        bindings[i] = value['assurance_bindings']
        inventories[i] = source_audit_scope(before.items[i], result)
        periods[i] = period_clarification_options(before.items[i], result, inventory=inventories[i])
    _, errors, feedback, retryable = check_meaning_contract(before, candidate, bindings, result=result,
        excerpts={p.page_number: p.text for p in result.document.pages}, inventories=inventories,
        periods=periods, assurance_bindings=bindings)
    assert retryable and set(feedback) == {'item_2'}
    assert any('status is missing' in error for error in errors)
    assert any('period is missing' in error for error in errors)
