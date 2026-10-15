"""Reviewer transport correction never relaxes audience, source or arithmetic checks."""
import copy
import json

import pytest

from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
from adaptive_document_agent.models.executive_brief import ExecutiveBrief, ExecutiveBriefItem, BriefQuote
from tests.test_executive_brief import result_for


def setup_review():
    text = 'Unaudited output rose from 12 units in 2023 to 18 units in 2024.'
    source = 'Unaudited output was 12 units in 2023 and 18 units in 2024.'
    item = ExecutiveBriefItem(label='Output change', text=text,
                              evidence=[BriefQuote(page=1, text=source)])
    fixed = ExecutiveBriefItem(label='Status', text='The figures are unaudited.',
                               evidence=[BriefQuote(page=1, text=source)])
    brief = ExecutiveBrief(items=[item, fixed])
    verdict = dict(index=0, accepted=True, reason='The comparison and audit status match the source.',
        numeric_comparison=True, comparisons=[dict(
            claim='Output rose from 12 units to 18 units.', start_value='12', end_value='18',
            direction='increase', start_ref='i0_q0', end_ref='i0_q0',
            start_duration_months=12, end_duration_months=12)])
    other = dict(index=1, accepted=True, reason='The source status is preserved.',
                 numeric_comparison=False, comparisons=[])
    corrected = copy.deepcopy(verdict)
    corrected['comparisons'][0]['claim'] = text
    return brief, result_for([source]), {'items': [verdict, other]}, {'items': [corrected]}


class Gateway:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(messages)
        assert kwargs['allow_repair'] is False
        return schema.model_validate(next(self.responses))


def test_exact_binding_correction_keeps_audience_sources_and_unchanged_items_memoized():
    brief, result, original, corrected = setup_review()
    before = brief.model_dump_json()
    gateway = Gateway([original, corrected])
    validate = meaning_validator(gateway, result=result)
    assert validate(brief) == {}
    assert validate(brief) == {}
    assert brief.model_dump_json() == before
    assert len(gateway.calls) == 2
    assert '"index": 1' not in gateway.calls[1][1]['content']
    assert 'label, paraphrase' in gateway.calls[1][-1]['content']
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'executive_brief_binding_audit'))
    assert audit['original'][0]['comparisons'][0]['claim'] == original['items'][0]['comparisons'][0]['claim']
    assert audit['response']['items'][0]['comparisons'][0]['claim'] == brief.items[0].text


@pytest.mark.parametrize('mutation', ['repeated_binding', 'erased_comparison', 'changed_source',
                                    'changed_direction', 'changed_endpoint', 'changed_duration',
                                    'reordered_comparisons', 'omitted_index'])
def test_invalid_binding_correction_fails_closed_after_one_attempt(mutation):
    brief, result, original, corrected = setup_review()
    row = corrected['items'][0]
    if mutation == 'repeated_binding':
        row['comparisons'][0]['claim'] = original['items'][0]['comparisons'][0]['claim']
    elif mutation == 'erased_comparison':
        row['numeric_comparison'] = False
        row['comparisons'] = []
    elif mutation == 'changed_source':
        row['comparisons'][0]['start_ref'] = 'i1_q0'
    elif mutation == 'changed_direction':
        row['comparisons'][0]['direction'] = 'decrease'
    elif mutation == 'changed_endpoint':
        row['comparisons'][0]['end_value'] = '19'
    elif mutation == 'changed_duration':
        row['comparisons'][0]['end_duration_months'] = 6
    elif mutation == 'reordered_comparisons':
        second = {**copy.deepcopy(row['comparisons'][0]), 'start_value': '18',
                  'end_value': '12', 'direction': 'decrease'}
        original['items'][0]['comparisons'].append(second)
        row['comparisons'].insert(0, second)
    else:
        corrected['items'] = []
    gateway = Gateway([original, corrected])
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    assert set(errors) == {0}
    assert validate(brief) == errors
    assert len(gateway.calls) == 2


@pytest.mark.parametrize('failure', ['direction', 'source', 'durations', 'qualification'])
def test_corrected_binding_still_runs_full_original_evidence_gates(failure):
    brief, result, original, corrected = setup_review()
    for response in (original, corrected):
        row = response['items'][0]
        comparison = row['comparisons'][0]
        if failure == 'direction':
            comparison['direction'] = 'decrease'
        elif failure == 'source':
            comparison['start_ref'] = 'other_item_quote'
        elif failure == 'durations':
            comparison['end_duration_months'] = 6
        else:
            row['accepted'] = False
            row['reason'] = 'Missing a source qualification.'
    gateway = Gateway([original, corrected])
    errors = meaning_validator(gateway, result=result)(brief)
    expected = 'outside' if failure == 'source' else failure
    assert any(expected in error for error in errors[0])
    assert len(gateway.calls) == 2


def test_binding_correction_cannot_accept_a_previously_rejected_meaning():
    brief, result, original, corrected = setup_review()
    original['items'][0].update(accepted=False, reason='Missing source audit status.')
    gateway = Gateway([original, corrected])
    errors = meaning_validator(gateway, result=result)(brief)
    assert any('cannot override' in error for error in errors[0])
    assert any('Missing source audit status' in error for error in errors[0])


def test_binding_correction_transport_failure_is_audited_without_content_retry():
    from adaptive_document_agent.services.llm.exceptions import LLMTransportError
    brief, result, original, _ = setup_review()

    class FailingGateway(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            if self.calls:
                self.calls.append(messages)
                raise LLMTransportError('Temporary provider failure')
            return super().generate_structured(messages, schema, **kwargs)

    gateway = FailingGateway([original])
    with pytest.raises(LLMTransportError, match='Temporary provider failure'):
        meaning_validator(gateway, result=result)(brief)
    assert len(gateway.calls) == 2
    audit = json.loads(next(w.message for w in result.validation_warnings
                           if w.code == 'executive_brief_binding_audit'))
    assert 'transport failure' in audit['errors']['0'][0]
