"""Repair reviewer bindings before rewriting correct, immutable audience copy."""
from concurrent.futures import CancelledError
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.brief_claim_direction import BriefClaimDirectionReview
from adaptive_document_agent.agent.brief_meaning_review import BriefMeaningReview, meaning_validator
from adaptive_document_agent.models.executive_brief import BriefQuote, ExecutiveBrief, ExecutiveBriefItem
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from tests.test_executive_brief import result_for


class ScriptedGateway:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((deepcopy(messages), schema, kwargs))
        assert kwargs['stage'] == 'report' and kwargs['allow_repair'] is False
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return schema.model_validate(output)


def loss_fixture():
    # Captured .028 heading/body wording and coefficients; the source fixture
    # keeps the relevant literal table rows without needing a private JSON file.
    label = 'Losses widen as revenue grows'
    text = ('Revenue was RMB 286749 thousand in FY2023 versus RMB 241013 thousand in FY2022, '
            'while loss before tax was RMB -89800 thousand versus RMB -52612 thousand.')
    source = ('Year ended December 31,\n2022 2023\n(RMB in thousands)\n'
              'Revenue 241,013 286,749\nLoss before tax (52,612) (89,800)')
    item = ExecutiveBriefItem(label=label, text=text, evidence=[BriefQuote(page=1, text=source)])
    facts = [text.split(', while ')[0], text.split(', while ')[1].rstrip('.')]
    def comparison(claim, start, end, magnitude):
        return dict(claim=claim, start_value=start, end_value=end, direction='increase',
            absolute_magnitude=magnitude, start_ref='i0_q0', end_ref='i0_q0',
            start_duration_months=12, end_duration_months=12)
    original = dict(items=[dict(index=0, accepted=True, reason='The dated source values match.',
        numeric_comparison=True, comparisons=[comparison(facts[0], '241013', '286749', False),
                                              comparison(facts[1], '-52612', '-89800', True)])])
    initial_direction = dict(items=[dict(index=0, comparisons=[dict(comparison_index=i, claim=claim,
        predicate='', direction='not_asserted', absolute_magnitude=bool(i),
        reason='The claim lists dated facts without asserting a direction.') for i, claim in enumerate(facts)],
        omitted_directional_claims=['Losses widen', 'revenue grows'])])
    corrected = dict(items=[dict(index=0, accepted=True,
        reason='Both heading directions and all separately stated facts are supported.', numeric_comparison=True,
        comparisons=[comparison('Losses widen', '-52612', '-89800', True),
                     comparison('revenue grows', '241013', '286749', False)])])
    final_direction = dict(items=[dict(index=0, comparisons=[dict(comparison_index=i, claim=claim,
        predicate=predicate, direction='increase', absolute_magnitude=magnitude,
        reason='The exact heading predicate asserts this measure direction.')
        for i, (claim, predicate, magnitude) in enumerate([
            ('Losses widen', 'widen', True), ('revenue grows', 'grows', False)])],
        omitted_directional_claims=[])])
    return ExecutiveBrief(items=[item]), result_for([source]), original, initial_direction, corrected, final_direction


def test_observed_dated_facts_and_unbound_heading_are_corrected_without_content_rewrite():
    brief, result, original, initial, corrected, final = loss_fixture()
    before = brief.model_dump_json(), result.document.model_dump_json()
    gateway = ScriptedGateway([original, initial, corrected, final])
    validate = meaning_validator(gateway, result=result)
    assert validate(brief) == {} and validate(brief) == {}
    assert len(gateway.calls) == 4
    assert [schema for _, schema, _ in gateway.calls] == [BriefMeaningReview, BriefClaimDirectionReview] * 2
    # The source reviewer receives the original full catalog and audience
    # payload; the new independent predicate reader receives no source verdict.
    assert gateway.calls[2][0][:2] == gateway.calls[0][0][:2]
    assert 'requested_indices' in gateway.calls[2][0][2]['content']
    assert before == (brief.model_dump_json(), result.document.model_dump_json())
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'executive_brief_comparison_correction_audit'))
    assert audit['status'] == 'accepted' and not audit['errors']
    assert audit['original']['items'][0]['comparisons'][0]['claim'] == original['items'][0]['comparisons'][0]['claim']
    assert audit['response']['items'][0]['comparisons'][0]['claim'] == 'Losses widen'


def test_unasserted_facts_still_fail_until_source_review_removes_the_false_comparison():
    brief, result, original, initial, _, _ = loss_fixture()
    brief.items[0].label = 'Reported results'
    initial['items'][0]['omitted_directional_claims'] = []
    corrected = dict(items=[dict(index=0, accepted=True, reason='All dated facts remain source-verified.',
                                numeric_comparison=False, comparisons=[])])
    final = dict(items=[dict(index=0, comparisons=[], omitted_directional_claims=[])])
    gateway = ScriptedGateway([original, initial, corrected, final])
    assert meaning_validator(gateway, result=result)(brief) == {}
    assert len(gateway.calls) == 4


def test_observed_shared_predicate_rebinds_a_continuous_clause_and_both_heading_measures():
    label = 'Six-axis ASP falls as volume rises'
    text = ('The six-axis ASP declined to RMB 56.6 thousand per unit in FY2023 from RMB 61.4 thousand '
            'per unit in FY2022, and to RMB 47.1 thousand per unit in 1H2024 from RMB 58.6 thousand '
            'per unit in 1H2023, even as first-half volume rose to 1,354 units from 898.')
    source = ('Year ended December 31, 2022 2023; Six months ended June 30, 2023 2024\n'
              'Sales volume ASP (RMB in thousands/unit for ASP)\n'
              'Six-axis cobots 1,707 61.4 2,374 56.6 898 58.6 1,354 47.1')
    item = ExecutiveBriefItem(label=label, text=text, evidence=[BriefQuote(page=1, text=source)])
    first = text.split(', and ')[0]
    fragment = text.split(', and ')[1].split(', even as ')[0]
    volume = text.split(', even as ')[1].rstrip('.')
    complete = text.split(', even as ')[0]
    def comparison(claim, start, end, direction, months):
        return dict(claim=claim, start_value=start, end_value=end, direction=direction,
            start_ref='i0_q0', end_ref='i0_q0', start_duration_months=months, end_duration_months=months)
    original = dict(items=[dict(index=0, accepted=True, reason='Source endpoints match.', numeric_comparison=True,
        comparisons=[comparison(first, '61.4', '56.6', 'decrease', 12),
                     comparison(fragment, '58.6', '47.1', 'decrease', 6),
                     comparison(volume, '898', '1,354', 'increase', 6)])])
    fixed = deepcopy(original)
    fixed['items'][0]['comparisons'][1]['claim'] = complete
    fixed['items'][0]['comparisons'].extend([
        comparison('Six-axis ASP falls', '61.4', '56.6', 'decrease', 12),
        comparison('volume rises', '898', '1,354', 'increase', 6)])
    def direction(review, *, first_pass):
        return dict(items=[dict(index=0, comparisons=[dict(comparison_index=i, claim=row['claim'],
            predicate='' if first_pass and i == 1 else ('declined' if i < 2 else 'rose' if i == 2 else
                'falls' if i == 3 else 'rises'),
            direction='not_asserted' if first_pass and i == 1 else row['direction'],
            absolute_magnitude=False, reason='Read only the exact predicate in this audience substring.')
            for i, row in enumerate(review['items'][0]['comparisons'])],
            omitted_directional_claims=['Six-axis ASP falls', 'volume rises'] if first_pass else [])])
    gateway = ScriptedGateway([original, direction(original, first_pass=True), fixed, direction(fixed, first_pass=False)])
    brief = ExecutiveBrief(items=[item])
    assert meaning_validator(gateway, result=result_for([source]))(brief) == {}
    assert brief.items[0] == item and len(gateway.calls) == 4


@pytest.mark.parametrize('source_direction', ['increase', 'decrease'])
def test_rebinding_a_false_loss_heading_cannot_clear_either_arithmetic_or_predicate_gate(source_direction):
    brief, result, original, initial, corrected, final = loss_fixture()
    brief.items[0].label = 'Losses narrow as revenue grows'
    initial['items'][0]['omitted_directional_claims'][0] = 'Losses narrow'
    corrected['items'][0]['comparisons'][0].update(claim='Losses narrow', direction=source_direction)
    final['items'][0]['comparisons'][0].update(claim='Losses narrow', predicate='narrow', direction='decrease')
    gateway = ScriptedGateway([original, initial, corrected, *([final] if source_direction == 'increase' else [])])
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    assert 'direction contradicts' in str(errors)
    assert validate(brief) == errors and len(gateway.calls) == (4 if source_direction == 'increase' else 3)


def test_binding_correction_only_rechecks_failed_items_and_preserves_other_verified_memo_entries():
    brief, result, original, initial, corrected, final = loss_fixture()
    other = ExecutiveBriefItem(label='Reported revenue', text='Revenue was RMB 286749 thousand in FY2023.',
                              evidence=deepcopy(brief.items[0].evidence))
    brief.items.append(other)
    original['items'].append(dict(index=1, accepted=True, reason='The reported fact is source-supported.',
                                 numeric_comparison=False, comparisons=[]))
    initial['items'].append(dict(index=1, comparisons=[], omitted_directional_claims=[]))
    gateway = ScriptedGateway([original, initial, corrected, final])
    validate = meaning_validator(gateway, result=result)
    assert validate(brief) == {} and validate(brief) == {} and len(gateway.calls) == 4
    payload = json.loads(gateway.calls[3][0][1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert [row['index'] for row in payload] == [0]
    assert gateway.calls[2][0][:2] == gateway.calls[0][0][:2]  # Complete original sources retained.


@pytest.mark.parametrize('mutation', ['source', 'direction', 'duration', 'qualification', 'binding', 'empty'])
def test_corrected_source_comparisons_must_pass_every_original_evidence_gate(mutation):
    brief, result, original, initial, corrected, final = loss_fixture()
    row = corrected['items'][0]
    if mutation == 'source':
        row['comparisons'][0]['start_ref'] = 'other_item_quote'
    elif mutation == 'direction':
        row['comparisons'][0]['direction'] = 'decrease'
    elif mutation == 'duration':
        row['comparisons'][0]['end_duration_months'] = 6
    elif mutation == 'qualification':
        row.update(accepted=False, reason='The source qualification is missing.')
    elif mutation == 'binding':
        row['comparisons'][0]['claim'] = 'Invented heading comparison'
    else:
        row['comparisons'] = []
    gateway = ScriptedGateway([original, initial, corrected])
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    assert errors and validate(brief) == errors and len(gateway.calls) == 3
    assert not gateway.outputs


def test_erased_real_heading_obligation_is_caught_by_fresh_independent_review_and_never_loops():
    brief, result, original, initial, corrected, final = loss_fixture()
    corrected['items'][0].update(numeric_comparison=False, comparisons=[])
    final['items'][0].update(comparisons=[], omitted_directional_claims=['Losses widen', 'revenue grows'])
    gateway = ScriptedGateway([original, initial, corrected, final])
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    assert 'lacks its own source-bound comparison' in str(errors)
    assert validate(brief) == errors and len(gateway.calls) == 4
    assert json.loads(result.validation_warnings[-1].message)['status'] == 'rejected'


@pytest.mark.parametrize('failure', ['indices', 'format'])
def test_source_comparison_correction_has_one_attempt_and_retains_original_diagnostics(failure):
    brief, result, original, initial, _, _ = loss_fixture()
    response = dict(items=[]) if failure == 'indices' else LLMStructuredOutputError(
        'Invalid review', response=LLMResponse(text='broken'))
    gateway = ScriptedGateway([original, initial, response])
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    assert 'not asserted' in str(errors) and 'Source comparison correction failed' in str(errors)
    assert validate(brief) == errors and len(gateway.calls) == 3


@pytest.mark.parametrize('failure', [CancelledError('stop'), PrivacyViolationError('local only'),
                                   LLMTransportError('offline')])
@pytest.mark.parametrize('stage', ['source_correction', 'fresh_direction'])
def test_interrupted_correction_never_memoizes_success_and_preserves_transport_boundaries(failure, stage):
    brief, result, original, initial, corrected, final = loss_fixture()
    first = [original, initial, failure] if stage == 'source_correction' else [original, initial, corrected, failure]
    gateway = ScriptedGateway([*first, original, initial, corrected, final])
    validate = meaning_validator(gateway, result=result)
    with pytest.raises(type(failure)):
        validate(brief)
    assert validate(brief) == {} and validate(brief) == {}
    assert len(gateway.calls) == len(first) + 4
    records = [json.loads(w.message) for w in result.validation_warnings
               if w.code == 'executive_brief_comparison_correction_audit']
    assert [r['status'] for r in records] == ['interrupted', 'accepted']


@pytest.mark.parametrize('wrong_body', [False, True])
def test_later_item_format_failure_cannot_leak_earlier_repair_eligibility(wrong_body):
    from tests.test_brief_direction_v174 import observed_loss
    brief, result, source, final = observed_loss(wrong_body=wrong_body)
    brief.items.append(brief.items[0].model_copy(deep=True))
    source.items.append(source.items[0].model_copy(deep=True, update={'index': 1}))
    final.items.append(final.items[0].model_copy(deep=True, update={'index': 1}))
    broken = final.model_copy(deep=True)
    # The first item records a repairable error before the second item breaks
    # the response's index contract. None of that attempt is authoritative.
    for comparison in broken.items[0].comparisons:
        comparison.direction = 'not_asserted'
        comparison.predicate = ''
    broken.items[1].comparisons[1].comparison_index = 0
    gateway = ScriptedGateway([source.model_dump(), broken.model_dump(), final.model_dump()])
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    if wrong_body:
        assert set(errors) == {0, 1}
        assert 'Audience predicate direction contradicts' in str(errors)
    else:
        assert errors == {}
    assert validate(brief) == errors
    # A successful format recovery needs no source correction; an actual
    # contradiction goes directly to content repair, never reviewer correction.
    assert [schema for _, schema, _ in gateway.calls] == [
        BriefMeaningReview, BriefClaimDirectionReview, BriefClaimDirectionReview]
    assert not any(w.code == 'executive_brief_comparison_correction_audit'
                   for w in result.validation_warnings)
