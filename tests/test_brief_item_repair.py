"""Item patches cannot rewrite verified copy or relax the existing source gates."""
import copy
import json

import pytest

from adaptive_document_agent.agent.executive_brief import ExecutiveBriefWriter
from adaptive_document_agent.models import PresentationPlan, PresentationSlide
from adaptive_document_agent.services.executive_brief import validate_executive_brief
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMTransportError
from adaptive_document_agent.services.llm.usage import LLMUsage
from tests.test_executive_brief import gateway, payload, result_for


def item(text, page=1, label='Finding'):
    value = payload(text, page, label)['items'][0]
    value['quantity_representations'] = []
    return value


def audited(result):
    return json.loads(next(issue.message for issue in result.validation_warnings
                           if issue.code == 'executive_brief_repair_audit'))


def capture_schemas(gateway):
    captured = []
    generate = gateway.generate_structured

    def recording(messages, response_model, **kwargs):
        captured.append((response_model.model_json_schema(), kwargs))
        return generate(messages, response_model, **kwargs)

    gateway.generate_structured = recording
    return captured


@pytest.mark.parametrize('failure', ['numbers', 'currency', 'scale', 'citation', 'missing_field', 'long_text', 'extra_field'])
def test_only_invalid_position_is_writable_and_all_locked_copy_is_exact(failure):
    texts = ['Revenue was USD 12 million in 2025.', 'Costs were USD 8 million in 2025.',
             'Cash was USD 4 million in 2025.']
    original = {'title': 'Material findings', 'items': [item(text, i + 1, f'Measure {i + 1}')
                                                     for i, text in enumerate(texts)]}
    # Numeric labels also need literal support; these fixture labels are purely editorial.
    for i, value in enumerate(original['items']):
        value['label'] = ['Revenue', 'Costs', 'Cash'][i]
    bad = original['items'][1]
    if failure == 'numbers':
        bad['text'] = texts[1].replace('8', '99')
    elif failure == 'currency':
        bad['text'] = texts[1].replace('USD', 'RMB')
    elif failure == 'scale':
        bad['text'] = texts[1].replace('million', 'billion')
    elif failure == 'citation':
        bad['evidence'][0]['page'] = 1
    elif failure == 'missing_field':
        del bad['evidence']
    elif failure == 'long_text':
        bad['text'] = texts[1] * 30
    else:
        bad['invented'] = True
    before = copy.deepcopy(original)
    patch = {'item_1': item(texts[1], 2, 'Costs')}
    result = result_for(texts)
    g, client = gateway([original, patch]); schemas = capture_schemas(g)
    brief = ExecutiveBriefWriter(g).generate(result)
    assert original == before
    assert brief.items[0].model_dump() == before['items'][0]
    assert brief.items[2].model_dump() == before['items'][2]
    assert brief.items[1].model_dump() == patch['item_1']
    assert brief.title == before['title']
    assert not validate_executive_brief(brief, result)
    assert len(client.calls) == 2
    assert all(not args['allow_repair'] for _, args in schemas)
    schema = schemas[1][0]
    assert schema['title'] == 'ExecutiveBriefPatch'
    assert set(schema['properties']) == {'item_1'} and not schema['additionalProperties']
    audit = audited(result)
    assert audit['original'] == before and audit['patch'] == patch
    assert audit['locked_indices'] == [0, 2] and audit['outcome'] == 'repaired'


def test_later_duplicate_is_invalid_before_locking_and_repaired_in_place():
    first, second = 'Revenue was 12.', 'Costs were 8.'
    original = payload(first); original['items'].append(item(first, label='Repeated'))
    result = result_for([first + ' ' + second])
    g, _ = gateway([original, {'item_1': item(second, label='Costs')}]); schemas = capture_schemas(g)
    brief = ExecutiveBriefWriter(g).generate(result)
    assert brief.items[0].model_dump() == original['items'][0]
    assert brief.items[1].text == second
    assert set(schemas[1][0]['properties']) == {'item_1'}
    assert audited(result)['locked_indices'] == [0]


@pytest.mark.parametrize('patch_kind', ['locked_field', 'whole_brief', 'missing_patch', 'invalid_patch', 'duplicate_locked'])
def test_patch_cannot_edit_locks_or_bypass_checks_and_never_gets_a_second_repair(patch_kind):
    first, second = 'Revenue was 12.', 'Costs were 8.'
    bad = item('Costs were 99.'); bad['evidence'] = [{'page': 1, 'text': second}]
    original = {'title': 'Findings', 'items': [item(first), bad]}
    corrected = item(second)
    patches = {
        'locked_field': {'item_0': item(first, label='Changed'), 'item_1': corrected},
        'whole_brief': {'title': 'Replacement', 'items': [item(first), corrected]},
        'missing_patch': {},
        'invalid_patch': {'item_1': bad},
        'duplicate_locked': {'item_1': item(first)},
    }
    result = result_for([first + ' ' + second])
    g, client = gateway([original, patches[patch_kind], {'item_1': corrected}])
    with pytest.raises(ValueError, match='evidence checks'):
        ExecutiveBriefWriter(g).generate(result)
    assert len(client.calls) == 2
    assert audited(result)['outcome'] == 'rejected'
    assert audited(result)['original']['items'][0] == original['items'][0]


@pytest.mark.parametrize('title', ['Unsupported 99', '', 'x' * 101, 123])
def test_invalid_title_gets_only_a_title_patch(title):
    source = 'Revenue was 12.'
    original = payload(source); original['title'] = title
    result = result_for([source])
    g, client = gateway([original, {'title': 'Verified findings'}]); schemas = capture_schemas(g)
    brief = ExecutiveBriefWriter(g).generate(result)
    assert brief.title == 'Verified findings'
    assert brief.items[0].model_dump() == original['items'][0]
    assert set(schemas[1][0]['properties']) == {'title'}
    assert len(client.calls) == 2


def test_patch_preserves_every_supplied_excerpt_including_correct_page_and_adjacent_definition():
    definition = 'Our processing rate refers to the average hourly output.'
    source = 'The processing rate was 24 units.'
    late = 'The estimate excludes extraordinary demand.'
    result = result_for([definition, source + ' Context.' * 520 + ' ' + late] + ['Background context.'] * 10)
    bad = payload(source, page=1)  # Wrong page cannot be the only retrieval filter.
    corrected = item(source, 2)
    corrected['evidence'].append({'page': 1, 'text': definition})
    g, client = gateway([{'pages': [2]}, bad, {'item_0': corrected}])
    brief = ExecutiveBriefWriter(g).generate(result)
    original_request, repair_request = client.calls[1][1]['content'], client.calls[2][1]['content']
    assert definition in original_request and definition in repair_request
    assert late in original_request and late in repair_request  # Past the old 4,000-char retry cut.
    assert not validate_executive_brief(brief, result)
    assert len(client.calls) == 3


def topics(result):
    result.presentation_plan = PresentationPlan(title='Review', slides=[
        PresentationSlide(id=f'topic-{i}', slide_type='analysis', title=f'Topic {i}', source_pages=[i])
        for i in (1, 2, 3)])


def test_missing_topic_additions_keep_locks_and_uncovered_source_anchors():
    texts = ['Revenue was 12.', 'Costs were 8.', 'Cash was 4.']
    result = result_for(texts); topics(result)
    original = payload(texts[0])
    g, client = gateway([original, {'additions': [item(texts[1], 2)]}]); schemas = capture_schemas(g)
    brief = ExecutiveBriefWriter(g).generate(result)
    assert brief.items[0].model_dump() == original['items'][0]
    assert set(schemas[1][0]['properties']) == {'additions'}
    assert schemas[1][0]['properties']['additions']['maxItems'] == 6
    assert all(text in client.calls[1][1]['content'] for text in texts)


def test_seven_locked_items_missing_topic_coverage_fail_without_replacing_one():
    findings = [f'Measure {i} was reported.' for i in range(7)]
    result = result_for([' '.join(findings), 'Other measure was 8.', 'Third measure was 4.']); topics(result)
    original = {'title': 'Findings', 'items': [item(text) for text in findings]}
    g, client = gateway([original])
    with pytest.raises(ValueError, match='seven verified items'):
        ExecutiveBriefWriter(g).generate(result)
    assert len(client.calls) == 1
    assert audited(result)['locked_indices'] == list(range(7))
    assert audited(result)['original'] == original


@pytest.mark.parametrize('raw', [
    '{}', '{"items": []}', '{"items": {}}', '{"title": "Findings"}',
    '{"items": [{"label": "bad"}], "unknown": true}',
    '{"items": [{"label": "bad"}], "title": "A", "title": "B"}',
    '{"items": [{"label": "bad", "label": "duplicate"}]}',
    '{"items": [{"label": 1e400}]}', '{"items": [{"label": NaN}]}', '{"items": [{"label": Infinity}]}',
    '{"items": [{"label": "bad"}]',
    '{"wrapper": {"items": [{"label": "bad"}]}}',
    'Prose {"items": [{"label": "bad"}]}',
    '{"items": [{"label": "bad"}]} {"items": [{"label": "other"}]}',
])
def test_unrecoverable_envelopes_fail_safely_without_fresh_synthesis(raw):
    result = result_for(['Revenue was 12.'])
    g, client = gateway([raw, payload('Revenue was 12.')])
    with pytest.raises(ValueError, match='safe recovery'):
        ExecutiveBriefWriter(g).generate(result)
    assert len(client.calls) == 1
    audit = audited(result)
    assert audit['original_response'] == raw and audit['outcome'] == 'rejected'


def test_even_complete_truncated_response_is_not_salvaged():
    result = result_for(['Revenue was 12.'])
    g, _ = gateway([])
    calls = []

    def truncated(*args, **kwargs):
        calls.append(kwargs)
        raise LLMStructuredOutputError('truncated', response=LLMResponse(
            text=json.dumps(payload('Revenue was 12.')),
            usage=LLMUsage(provider='mock', model='mock', finish_reason='length')))

    g.generate_structured = truncated
    with pytest.raises(ValueError, match='Truncated'):
        ExecutiveBriefWriter(g).generate(result)
    assert len(calls) == 1 and audited(result)['outcome'] == 'rejected'


def test_failed_patch_salvage_keeps_all_original_locks_even_when_patch_precedes_duplicate():
    texts = ['Revenue was 12.', 'Costs were 8.', 'Cash was 4.']
    bad = item('Debt was 99.'); bad['evidence'] = [{'page': 1, 'text': texts[0]}]
    original = {'title': 'Findings', 'items': [bad, *[item(text) for text in texts]]}
    result = result_for([' '.join(texts)])
    g, client = gateway([original, {'item_0': item(texts[0], label='Should not displace lock')}])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert [value.model_dump() for value in brief.items] == original['items'][1:]
    audit = audited(result)
    assert audit['outcome'] == 'salvaged' and audit['discarded_indices'] == [0]
    warning = next(issue for issue in result.validation_warnings if issue.code == 'executive_brief_items_rejected')
    assert warning.severity == 'warning' and '[0]' in warning.message
    assert len(client.calls) == 2
    assert result.model_validate_json(result.model_dump_json()).validation_warnings == result.validation_warnings


def test_three_verified_items_cannot_salvage_failed_topic_coverage():
    texts = ['Revenue was 12.', 'Costs were 8.', 'Cash was 4.']
    result = result_for([' '.join(texts), 'Output was 20.', 'Staffing was 30.']); topics(result)
    original = {'title': 'Findings', 'items': [item(text) for text in texts]}
    g, client = gateway([original, {'additions': []}])
    with pytest.raises(ValueError, match='selected analytical topics'):
        ExecutiveBriefWriter(g).generate(result)
    assert len(client.calls) == 2 and audited(result)['outcome'] == 'rejected'


def test_transport_failure_is_audited_and_never_retried_as_content_repair():
    source = 'Revenue was 12.'
    bad = payload(source); bad['items'][0]['text'] = 'Revenue was 99.'
    result = result_for([source])
    g, client = gateway([bad])
    generate = g.generate_structured

    def failure(messages, response_model, **kwargs):
        if response_model.__name__ == 'ExecutiveBriefPatch':
            raise LLMTransportError('offline')
        return generate(messages, response_model, **kwargs)

    g.generate_structured = failure
    with pytest.raises(LLMTransportError, match='offline'):
        ExecutiveBriefWriter(g).generate(result)
    assert len(client.calls) == 1 and audited(result)['repair_errors'] == ['offline']


def test_salvage_cannot_accept_whitespace_title_from_failed_title_patch():
    texts = ['Revenue was 12.', 'Costs were 8.', 'Cash was 4.']
    original = {'title': 'Unsupported 99', 'items': [item(text) for text in texts]}
    result = result_for([' '.join(texts)])
    g, client = gateway([original, {'title': '   '}])
    brief = ExecutiveBriefWriter(g).generate(result)
    assert brief.title == 'Executive Summary'
    assert [value.model_dump() for value in brief.items] == original['items']
    assert audited(result)['outcome'] == 'salvaged'
    assert len(client.calls) == 2
