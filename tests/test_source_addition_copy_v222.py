"""A single overlong addition gets bounded copy repair, never automatic approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
from adaptive_document_agent.agent.source_integration_review import (
    review_supplementary_sources, resolved_source_check_ids,
)
from tests.test_budget_output_v145 import gateway, response
from tests.test_source_completion_capacity_v173 import _outputs, _audit
from tests.test_source_integration_v166 import fixture


@pytest.mark.parametrize('progress', [True, False])
def test_mixed_schema_correction_only_gets_copy_slot_after_strict_length_progress(progress):
    result, constraint = fixture()
    for i in range(5):
        text = f'Operational context {i}.'
        result.document.pages[0].text += '\n' + text
        result.executive_brief.items.append(ExecutiveBriefItem(label='Context', text=text,
            evidence=[dict(page=1, text=text)]))
    original = result.executive_brief.model_copy(deep=True)
    draft, review = _outputs(constraint)
    draft.decisions[0].brief_item_indexes = [len(original.items)]
    invalid = draft.model_dump(mode='json')
    invalid['additions'][0]['text'] = constraint * 20
    invalid['decisions'][0]['evidence'] *= 5
    corrected = draft.model_dump(mode='json')
    corrected['additions'][0]['text'] = constraint * (12 if progress else 20)
    outputs = [response(json.dumps(invalid)), response(json.dumps(corrected))]
    if progress:
        outputs.extend([response(json.dumps({'addition_0_text': constraint})), response(review)])
    llm, _ = gateway(outputs)
    merged = review_supplementary_sources(llm, result, original)
    assert bool(resolved_source_check_ids(result, merged)) is progress
    assert [u['operation'] for u in llm.usage] == ['SourceIntegrationDraft', 'SourceIntegrationDraft',
        *(['SourceAdditionCopy', 'SourceIntegrationReview'] if progress else [])]
    if progress:
        assert _audit(result)[1]['attempts'][1]['length_progress_retry']
        assert merged.items[:len(original.items)] == original.items


def test_truncated_copy_retries_identical_input_without_accepting_partial_json():
    from adaptive_document_agent.agent.source_integration_copy import shorten_additions
    from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
    _, constraint = fixture()
    draft, _ = _outputs(constraint)
    raw = draft.model_dump(mode='json')
    raw['additions'][0]['text'] = constraint * 12
    llm, client = gateway([response('{"addition_0_text":', finish='length'),
        response(json.dumps({'addition_0_text': constraint}))])
    entry = {}
    shortened = shorten_additions(llm, [], SourceIntegrationDraft,
        (raw, [dict(loc=['additions', 0, 'text'], ctx=dict(max_length=550))]), entry, 6)
    assert shortened.additions == draft.additions
    assert client.requests[0][0] == client.requests[1][0]
    assert [a['requested_max_tokens'] for a in entry['shortened_output_attempts']] == [8000, 16384]
    assert [a['status'] for a in entry['shortened_output_attempts']] == ['truncated', 'response_received']


@pytest.mark.parametrize('setting', ['reduced', 'provider_default'])
def test_source_copy_uses_configured_reduction_but_source_review_keeps_reasoning(setting):
    from adaptive_document_agent.services.llm import LLMSettings
    from adaptive_document_agent.services.llm.reasoning_policy import request_reasoning_policy
    settings = LLMSettings(provider='openai', model='gpt-6-luna', simple_task_reasoning=setting)
    copy = request_reasoning_policy(settings, stage='report', operation='SourceAdditionCopy', model=settings.model)
    review = request_reasoning_policy(settings, stage='report', operation='SourceIntegrationReview', model=settings.model)
    assert copy['options'] == ({'reasoning_effort': 'low'} if setting == 'reduced' else {})
    assert review['options'] == {}


@pytest.mark.parametrize('binding', ['quantity_representations', 'comparison_table'])
def test_copy_with_locked_numeric_structure_is_not_split(binding):
    from adaptive_document_agent.agent.source_integration_copy import shorten_additions
    from adaptive_document_agent.agent.source_integration_review import SourceIntegrationDraft
    _, constraint = fixture()
    draft, _ = _outputs(constraint)
    raw = draft.model_dump(mode='json')
    annotation = ([dict(quantity_text='HK$12 million', source_value='-12', representation='absolute_magnitude')]
                  if binding == 'quantity_representations' else dict(headers=['Year', 'Amount'], rows=[['2025', '(12)']]))
    raw['additions'][0][binding] = annotation
    raw['additions'][0]['text'] = constraint * 12
    llm, _ = gateway([response(json.dumps({'addition_0_text': constraint}))])
    pending = raw, [dict(loc=['additions', 0, 'text'], ctx=dict(max_length=550))]
    shortened = shorten_additions(llm, [], SourceIntegrationDraft, pending, {}, 1)
    assert len(shortened.additions) == 1
    assert shortened.model_dump(mode='json')['additions'][0][binding] == annotation
    assert shortened.decisions == draft.decisions


def test_semantic_revision_keeps_its_own_format_correction_after_initial_shortening():
    result, constraint = fixture()
    for i in range(5):
        text = f'Operational context {i}.'
        result.document.pages[0].text += '\n' + text
        result.executive_brief.items.append(ExecutiveBriefItem(label='Context', text=text,
            evidence=[dict(page=1, text=text)]))
    original = result.executive_brief.model_copy(deep=True)
    draft, review = _outputs(constraint)
    draft.decisions[0].brief_item_indexes = [len(original.items)]
    invalid = draft.model_dump(mode='json')
    invalid['additions'][0]['text'] = constraint * 20
    rejected = review.model_copy(deep=True)
    rejected.verdicts[0].accepted = False
    patch = response(json.dumps({'addition_0_text': constraint}))
    llm, _ = gateway([response(json.dumps(invalid)), patch, response(rejected),
        response(json.dumps(invalid)), patch, response(review)])
    merged = review_supplementary_sources(llm, result, original)
    assert resolved_source_check_ids(result, merged) == {'contracts'}
    assert len(_audit(result)[1]['attempts']) == 4
    assert [u['operation'] for u in llm.usage] == [
        'SourceIntegrationDraft', 'SourceAdditionCopy', 'SourceIntegrationReview',
        'SourceIntegrationDraft', 'SourceAdditionCopy', 'SourceIntegrationReview']
    assert merged.items[:len(original.items)] == original.items


@pytest.mark.parametrize('accepted', [False, True])
def test_shorter_complete_copy_stays_bounded_and_preserves_semantic_correction(accepted):
    result, constraint = fixture()
    for i in range(5):
        text = f'Operational context {i}.'
        result.document.pages[0].text += '\n' + text
        result.executive_brief.items.append(ExecutiveBriefItem(label='Context', text=text,
            evidence=[dict(page=1, text=text)]))
    original = result.executive_brief.model_copy(deep=True)
    draft, review = _outputs(constraint)
    draft.decisions[0].brief_item_indexes = [len(original.items)]
    invalid = draft.model_dump(mode='json')
    invalid['additions'][0]['text'] = constraint * 20
    shorter = constraint * 12
    assert 550 < len(shorter) < len(invalid['additions'][0]['text'])
    review.verdicts[0].accepted = accepted
    outputs = [response(json.dumps(invalid)),
        response(json.dumps({'addition_0_text': shorter})),
        response(json.dumps({'addition_0_text': constraint})), response(review)]
    if not accepted:
        outputs.extend([response(draft), response(review)])
    llm, _ = gateway(outputs)
    merged = review_supplementary_sources(llm, result, original)
    assert [u['operation'] for u in llm.usage] == [
        'SourceIntegrationDraft', 'SourceAdditionCopy', 'SourceAdditionCopy', 'SourceIntegrationReview',
        *([] if accepted else ['SourceIntegrationDraft', 'SourceIntegrationReview'])]
    audit = _audit(result)[1]
    assert len(audit['attempts']) == (3 if accepted else 4) and audit['attempts'][1]['length_progress_retry']
    assert audit['attempts'][2]['draft']['decisions'] == invalid['decisions']
    assert bool(resolved_source_check_ids(result, merged)) is accepted
    assert merged.items[:len(original.items)] == original.items
    if not accepted:
        assert merged == original


@pytest.mark.parametrize('slots', [1, 2])
@pytest.mark.parametrize('outcome', ['accepted', 'overlong', 'forged', 'rejected'])
def test_first_single_overlong_body_only_rewrites_requested_copy(slots, outcome):
    result, constraint = fixture()
    for label in ['Operations', 'Demand', 'Supply', 'Delivery', 'Planning'][:6 - slots]:
        text = f'{label} activities continued.'
        result.document.pages[0].text += '\n' + text
        result.executive_brief.items.append(ExecutiveBriefItem(
            label=label, text=text, evidence=[dict(page=1, text=text)]))
    original = result.executive_brief.model_copy(deep=True)
    source = deepcopy((result.document, result.observations))
    draft, review = _outputs(constraint)
    draft.decisions[0].brief_item_indexes = [len(original.items)]
    invalid = draft.model_dump(mode='json')
    invalid['additions'][0]['text'] = constraint * 12
    assert len(invalid['additions'][0]['text']) > 550
    text = constraint + (' Invented value 987654321.' if outcome == 'forged' else '')
    if outcome == 'overlong':
        text *= 12
    part = dict(label=draft.additions[0].label, text=text)
    patch = {'addition_0_text': text if slots == 1 else [part]}
    outputs = [response(json.dumps(invalid)), response(json.dumps(patch))]
    if outcome in {'accepted', 'rejected'}:
        review.verdicts[0].accepted = outcome == 'accepted'
        outputs.append(response(review))
        if outcome == 'rejected':
            outputs.extend([response(draft), response(review)])
    llm, client = gateway(outputs)

    merged = review_supplementary_sources(llm, result, original)
    assert result.executive_brief == original
    assert (result.document, result.observations) == source
    operations = [u['operation'] for u in llm.usage]
    assert operations[:2] == ['SourceIntegrationDraft', 'SourceAdditionCopy']
    request = client.requests[1][0]
    wire = next(m['content'] for m in request if m['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>'))
    packet = json.loads(wire.split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(packet) == {'fields_to_replace'}
    assert set(packet['fields_to_replace']) == {'addition_0_text'}
    assert packet['fields_to_replace']['addition_0_text']['maximum_characters'] == 550
    assert packet['fields_to_replace']['addition_0_text']['original'] == invalid['additions'][0]['text']
    assert packet['fields_to_replace']['addition_0_text']['locked_evidence'] == invalid['additions'][0]['evidence']
    if outcome == 'accepted':
        assert operations == ['SourceIntegrationDraft', 'SourceAdditionCopy', 'SourceIntegrationReview'], _audit(result)[1].get('reason')
        assert merged.items[:len(original.items)] == original.items
        assert merged.items[-1] == draft.additions[0]
        assert resolved_source_check_ids(result, merged) == {'contracts'}
        audit = _audit(result)[1]
        assert audit['attempts'][1]['draft']['decisions'] == invalid['decisions']
    else:
        assert merged == original and not resolved_source_check_ids(result, original)
        assert _audit(result)[0] == 'source_integration_unresolved'
        if outcome in {'overlong', 'forged'}:
            assert operations == ['SourceIntegrationDraft', 'SourceAdditionCopy']
        else:
            assert operations.count('SourceIntegrationReview') == 2
