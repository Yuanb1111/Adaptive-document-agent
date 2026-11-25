import json

import pytest

from adaptive_document_agent.agent.retained_description_revision import revise_descriptions
from adaptive_document_agent.agent.retained_page_sources import RetainedPage
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_retained_analysis_v216 import gateway


def source_page():
    evidence = [
        dict(page=2, text='The group said a larger share of orders arrived early.'),
        dict(page=3, text='Management considered the exposure limited.'),
    ]
    page = RetainedPage(title='Orders', message='The source reports order volumes.', source_context=[
        dict(scope='order timing', description='Reports earlier orders.', quote=evidence[0]),
        dict(scope='exposure assessment', description='Describes the exposure.', quote=evidence[1]),
        dict(scope='previous assessment', description='Describes previous conditions.', quote=evidence[1]),
    ])
    return page, evidence


def test_edits_only_addressed_descriptions_and_checks_provenance_of_earlier_wording():
    page, evidence = source_page()
    original = page.model_dump()
    prior = page.model_copy(deep=True)
    prior.source_context[0].description = 'Reports the changing share.'
    prior.source_context[1].scope = 'different population'
    prior.source_context[1].description = 'Reports an unrelated assessment.'
    purposes = {'context-0': 'Clarify that the mix changed.', 'context-1': 'Identify the speaker.'}
    edits = {'context-0': 'Reports that a larger share of orders arrived early.',
             'context-1': 'Describes management’s assessment that exposure was limited.'}
    mock = gateway([edits])
    revised = revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=500, prior_page=prior)
    expected = page.model_copy(deep=True)
    expected.source_context[0].description = edits['context-0']
    expected.source_context[1].description = edits['context-1']
    assert revised == expected and original == page.model_dump()
    assert [entry['operation'] for entry in mock.usage] == ['RetainedDescriptionRevision']
    data = json.loads(mock.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    items = data['addressed_descriptions']
    assert items.keys() == purposes.keys()
    assert items['context-0']['earlier_unapproved_wording'] == prior.source_context[0].description
    assert 'earlier_unapproved_wording' not in items['context-1']
    assert items['context-1']['correction'] == purposes['context-1']
    assert items['context-0']['literal_proof'] == [evidence[0]]


@pytest.mark.parametrize('fault', ['address', 'missing_reason', 'foreign_proof', 'scope'])
def test_ineligible_frozen_scope_proof_or_address_blocks_before_gateway(fault):
    page, evidence = source_page()
    purposes = {'context-0': 'Clarify this source discussion.'}
    if fault == 'address':
        purposes = {'context-00': 'Different address.'}
    elif fault == 'missing_reason':
        purposes = {'context-0': ' '}
    elif fault == 'foreign_proof':
        evidence[0] = {**evidence[0], 'page': 5}
    else:
        page.source_context[0].scope = 'FY2099'
    mock = gateway([])
    with pytest.raises(ValueError):
        revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=500)
    assert mock.client.calls == []


@pytest.mark.parametrize('response,limit,error', [
    ({'context-0': 'Reports a larger share.', 'context-1': 'Overwrites a sibling.'}, 500, LLMStructuredOutputError),
    ({'context-1': 'Reports the wrong ownership.'}, 500, LLMStructuredOutputError),
])
def test_rejected_response_never_mutates_page_or_retries(response, limit, error):
    page, evidence = source_page()
    original = page.model_dump()
    mock = gateway([response])
    with pytest.raises(error):
        revise_descriptions(mock, page, {'context-0': 'Clarify the share.'}, source_pages=evidence, periods=[], limit=limit)
    assert len(mock.client.calls) == 1 and original == page.model_dump()


@pytest.mark.parametrize('valid_alternative,over_capacity', [(True, False), (True, True), (False, False)])
def test_qualitative_repair_freezes_valid_siblings_checks_budget_and_keeps_numerical_proof(
        valid_alternative, over_capacity):
    page, evidence = source_page()
    proof = 'The group said the share of orders arriving early exceeded 40%.'
    page.source_context[0].quote.text = evidence[0]['text'] = proof
    original = page.model_dump()
    initial = 'Reports an early-order share above 40%.'
    if over_capacity:
        initial += ' Management discussed the timing of orders.' * 9
    valid = 'Reports a substantial share of orders arriving early.'
    sibling = 'Attributes the limited exposure assessment to management.'
    writer = {'context-0': initial, 'context-1': sibling}
    alternatives = {'context-0': dict(concise=initial, shorter=valid if valid_alternative else initial)}
    mock = gateway([writer, alternatives])
    reasons = {'context-0': 'Describe the order timing comparison.', 'context-1': 'Identify the speaker.'}
    if valid_alternative:
        revised = revise_descriptions(mock, page, reasons, source_pages=evidence, periods=[], limit=400)
        assert revised.source_context[0].description == valid
        assert revised.source_context[0].quote.text == proof
        assert revised.source_context[1].description == sibling
        assert revised.source_context[2] == page.source_context[2]
    else:
        with pytest.raises(ValueError, match='No complete length-repair alternative'):
            revise_descriptions(mock, page, reasons, source_pages=evidence, periods=[], limit=400)
    assert [call['operation'] for call in mock.usage] == ['RetainedDescriptionRevision', 'RetainedDescriptionLengthRepair']
    data = json.loads(mock.client.calls[1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert list(data['addressed_descriptions']) == ['context-0']
    item = data['addressed_descriptions']['context-0']
    assert 'percentage' in item['local_validation_error']
    assert item['complete_rejected_description'] == initial
    assert item['literal_proof'] == [evidence[0]]
    assert page.model_dump() == original


@pytest.mark.parametrize('fits', [True, False])
def test_page_overflow_repairs_only_the_contributing_edit_and_bounds_requests(fits):
    page, evidence = source_page()
    original = page.model_dump()
    purposes = {'context-0': 'Describe timing.', 'context-1': 'Identify the speaker.'}
    long = 'Reports a larger share. ' + 'Orders arrived early. ' * 14
    sibling = 'Attributes the assessment of limited exposure to management.'
    fitting = 'Reports a larger share of early orders.'
    first = {'context-0': long, 'context-1': sibling}
    second = {'context-0': dict(concise=long, shorter=fitting if fits else long)}
    mock = gateway([first, second])
    if fits:
        revised = revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=350)
        assert revised.source_context[0].description == fitting
        assert revised.source_context[1].description == sibling
        assert revised.source_context[2] == page.source_context[2]
    else:
        with pytest.raises(ValueError, match='No complete length-repair alternative'):
            revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=350)
    assert [row['operation'] for row in mock.usage] == ['RetainedDescriptionRevision', 'RetainedDescriptionLengthRepair']
    data = json.loads(mock.client.calls[1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert list(data['addressed_descriptions']) == ['context-0']
    assert page.model_dump() == original


def completed_mock(monkeypatch, responses, *, finish='stop', refusal=False):
    mock = gateway(responses)
    generate = mock.client.generate_text

    def reply(*args, **options):
        response = generate(*args, **options)
        response.usage.finish_reason = finish
        if refusal:
            response.raw = {'choices': [{'message': {'refusal': 'Refused.'}}]}
        return response

    monkeypatch.setattr(mock.client, 'generate_text', reply)
    return mock


@pytest.mark.parametrize('two_long', [True, False])
def test_length_repair_freezes_the_valid_response_and_selects_complete_fitting_alternatives(monkeypatch, two_long):
    page, evidence = source_page()
    purposes = {'context-0': 'Clarify the share.', 'context-1': 'Attribute the assessment.'}
    long = 'Reports earlier orders. ' * 33
    sibling = 'Attributes the exposure assessment to management.'
    first = {'context-0': long, 'context-1': long if two_long else sibling}
    fitting = 'Reports a larger share of orders arriving early.'
    second = {'context-0': dict(concise=long, shorter=fitting)}
    if two_long:
        second['context-1'] = dict(concise=sibling, shorter='Describes the assessed exposure.')
    mock = completed_mock(monkeypatch, [first, second])
    revised = revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=420)
    assert [row['operation'] for row in mock.usage] == ['RetainedDescriptionRevision', 'RetainedDescriptionLengthRepair']
    wire = json.loads(mock.client.calls[1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(wire['addressed_descriptions']) == set(second)
    assert wire['addressed_descriptions']['context-0']['complete_rejected_description'] == long
    assert revised.source_context[0].description == fitting
    assert revised.source_context[1].description == sibling
    assert revised.source_context[2] == page.source_context[2]
    assert revised.all_context_evidence == page.all_context_evidence
    assert revised.message == page.message and revised.title == page.title


@pytest.mark.parametrize('joint', [True, False])
def test_expanded_addressed_siblings_share_space_only_when_the_previous_copy_cannot_fit(monkeypatch, joint):
    from adaptive_document_agent.agent.retained_page_sources import authored_visible_copy

    page, evidence = source_page()
    original = 'Reports that orders were received early. ' * 4
    page.source_context[0].description = original.strip()
    page.source_context.append(page.source_context[2].model_copy(update={'scope': 'earlier period'}))
    proof = 'The group reports that the share of orders arriving early was above 40%.'
    page.source_context[0].quote.text = evidence[0]['text'] = proof
    first = {'context-0': 'Reports an early-order share above 40%. ' * 20,
             'context-1': 'Attributes the assessment of limited exposure to management. ' * 3,
             'context-2': 'Describes how management considered the earlier exposure limited. ' * 3}
    compact = {'context-0': 'Reports a substantial share of early orders.',
               'context-1': 'Attributes limited exposure to management.',
               'context-2': 'Reports management saw limited exposure.'}

    def visible_length(first_text, second_text, third_text):
        candidate = page.model_copy(deep=True)
        for item, text in zip(candidate.source_context, [first_text, second_text, third_text]):
            item.description = text
        return len(authored_visible_copy(candidate, []))

    if joint:
        # Both expansions fit individually with a corrected first slot, but not together.
        limit = max(visible_length(compact['context-0'], first['context-1'], compact['context-2']),
                    visible_length(compact['context-0'], compact['context-1'], first['context-2']))
        assert visible_length(original, first['context-1'], first['context-2']) > limit
        assert visible_length(*compact.values()) <= limit < visible_length(
            compact['context-0'], first['context-1'], first['context-2'])
    else:
        limit = visible_length(original, first['context-1'], first['context-2']) + 1
    alternatives = {slot: dict(concise=text, shorter=text) for slot, text in compact.items()
                    if joint or slot == 'context-0'}
    mock = completed_mock(monkeypatch, [first, alternatives])
    purposes = {slot: 'Clarify the interpretation of the reported exposure and timing.' for slot in first}
    revised = revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=limit)

    assert [call['operation'] for call in mock.usage] == ['RetainedDescriptionRevision', 'RetainedDescriptionLengthRepair']
    data = json.loads(mock.client.calls[1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(data['addressed_descriptions']) == set(alternatives)
    assert 'percentage' in data['addressed_descriptions']['context-0']['local_validation_error']
    assert sum(revised.source_context[i].description == first[f'context-{i}'] for i in (1, 2)) == (1 if joint else 2)
    assert revised.source_context[0].description == compact['context-0']
    assert revised.source_context[3] == page.source_context[3]
    assert revised.all_context_evidence == page.all_context_evidence
    assert len(authored_visible_copy(revised, [])) <= limit


@pytest.mark.parametrize('fault', ['duplicate', 'trailing', 'type', 'extra', 'truncated', 'refusal', 'invalid_sibling'])
def test_only_complete_unambiguous_length_failure_can_start_second_call(monkeypatch, fault):
    page, evidence = source_page()
    long = 'Reports the conditions of delayed orders. ' * 20
    record = {'context-0': long, 'context-1': 'Describes local conditions.'}
    first = json.dumps(record)
    if fault == 'duplicate':
        first = first[:-1] + ',"context-0":' + json.dumps(long) + '}'
    elif fault == 'trailing':
        first += ' More text.'
    elif fault == 'type':
        first = {**record, 'context-1': ['wrong type']}
    elif fault == 'extra':
        first = {**record, 'context-2': 'Changes another finding.'}
    elif fault == 'invalid_sibling':
        first = {**record, 'context-1': 'Reports a larger share of 80%.'}
    mock = completed_mock(monkeypatch, [first], finish='length' if fault == 'truncated' else 'stop',
                          refusal=fault == 'refusal')
    with pytest.raises((LLMStructuredOutputError, ValueError)):
        revise_descriptions(mock, page, {'context-0': 'Clarify timing.', 'context-1': 'Clarify who assessed exposure.'},
                            source_pages=evidence, periods=[], limit=450)
    assert len(mock.client.calls) == 1


@pytest.mark.parametrize('second', [
    {'context-0': dict(concise='Reports an incorrect rate of 40%.', shorter='The reported share was 30%.')},
    {'context-0': dict(concise='Reports earlier orders.')},
    {'context-0': dict(concise='Reports earlier orders. ' * 18, shorter='Describes earlier orders. ' * 16)},
])
def test_unusable_length_repair_fails_without_a_third_call(monkeypatch, second):
    page, evidence = source_page()
    original = page.model_dump()
    mock = completed_mock(monkeypatch, [{'context-0': 'Describes order timing. ' * 36}, second])
    with pytest.raises((LLMStructuredOutputError, ValueError)):
        revise_descriptions(mock, page, {'context-0': 'Clarify order timing.'}, source_pages=evidence,
                            periods=[], limit=420)
    assert len(mock.client.calls) == 2 and original == page.model_dump()


@pytest.mark.parametrize('fault', [None, 'valid_noop', 'noop_only', 'ambiguous_noop', 'overlapping_noop',
                                   'bad_second_response', 'unknown_slot', 'ambiguous_anchor', 'overlap',
                                   'entire_original', 'unbound', 'over_capacity'])
def test_joint_repair_can_patch_original_clauses_once_without_changing_other_copy(monkeypatch, fault):
    from adaptive_document_agent.agent.retained_page_sources import authored_visible_copy

    page, evidence = source_page()
    page.source_context[0].description = 'Reports earlier orders. The group monitored the orders.'
    original = page.model_dump()
    limit = len(authored_visible_copy(page, [])) + 60
    first = {'context-0': 'Reports the share of early orders above 40%. ' * 19,
             'context-1': 'Attributes the limited exposure assessment to management. ' * 3}
    invalid = 'Reports a share above 40%.'
    second = {slot: dict(concise=invalid, shorter=invalid) for slot in first}
    corrected = dict(before='earlier orders', after='a larger share of early orders')
    assessment = dict(before='the exposure', after='management’s assessment of limited exposure')
    third = {'context-0': dict(concise=[dict(before='not in this text', after='x')], shorter=[corrected]),
             'context-1': dict(concise=[assessment], shorter=[assessment])}
    if fault == 'bad_second_response':
        del second['context-1']['shorter']
    elif fault == 'unknown_slot':
        third['context-00'] = third.pop('context-0')
    elif fault == 'ambiguous_anchor':
        third['context-0']['shorter'] = [dict(before='orders', after='other orders')]
    elif fault == 'overlap':
        third['context-0']['shorter'] = [corrected, dict(before='earlier', after='early')]
    elif fault == 'valid_noop':
        third['context-0']['shorter'].append(dict(before='The group', after='The group'))
    elif fault == 'noop_only':
        third['context-0']['shorter'] = [dict(before='The group', after='The group')]
    elif fault == 'ambiguous_noop':
        third['context-0']['shorter'].append(dict(before='orders', after='orders'))
    elif fault == 'overlapping_noop':
        third['context-0']['shorter'].append(dict(before='earlier', after='earlier'))
    elif fault == 'entire_original':
        third['context-0']['shorter'] = [dict(before=page.source_context[0].description, after='Reports early orders.')]
    elif fault == 'unbound':
        third['context-0']['shorter'] = [dict(before='earlier orders', after='an early-order share of 45%')]
    elif fault == 'over_capacity':
        third['context-0']['shorter'] = [dict(before='earlier orders', after='the share of earlier orders ' * 14)]
    mock = completed_mock(monkeypatch, [first, second, third])
    purposes = {'context-0': 'Clarify the change in share.', 'context-1': 'Identify the speaker.'}
    if fault is None or fault == 'valid_noop':
        revised = revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=limit)
        assert revised.source_context[0].description == (
            'Reports a larger share of early orders. The group monitored the orders.')
        assert revised.source_context[1].description == 'Describes management’s assessment of limited exposure.'
        assert revised.source_context[2] == page.source_context[2]
        assert revised.all_context_evidence == page.all_context_evidence
        assert len(authored_visible_copy(revised, [])) <= limit
    else:
        with pytest.raises((ValueError, LLMStructuredOutputError)):
            revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=limit)
    expected = ['RetainedDescriptionRevision', 'RetainedDescriptionLengthRepair']
    if fault != 'bad_second_response':
        expected.append('RetainedDescriptionSpanRepair')
        data = json.loads(mock.client.calls[-1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        assert data['addressed_descriptions']['context-0']['current_description'] == page.source_context[0].description
        assert data['addressed_descriptions']['context-1']['unsuccessful_alternatives'] == second['context-1']
        assert data['shared_remaining_characters'] == 60
    assert [u['operation'] for u in mock.usage] == expected
    assert page.model_dump() == original


def test_positive_growth_from_both_sparse_sets_can_share_a_valid_paid_complete_sibling(monkeypatch):
    from adaptive_document_agent.agent.retained_page_sources import authored_visible_copy

    page, evidence = source_page()
    first = {'context-0': 'Reports an early share above 40%. ' * 24,
             'context-1': 'Attributes the assessment of exposure to management. ' * 4}
    reusable = 'Relays management’s view.'
    invalid = 'Reports an unbound rate of 40%.'
    second = {'context-0': dict(concise=invalid, shorter=invalid),
              'context-1': dict(concise=invalid, shorter=reusable)}
    third = {'context-0': dict(
        concise=[dict(before='earlier', after='a materially larger share of early')],
        shorter=[dict(before='earlier', after='a larger share of early')]),
        'context-1': dict(
        concise=[dict(before='the exposure', after='management’s assessment that exposure remained limited')],
        shorter=[dict(before='the exposure', after='management’s assessment of limited exposure')])}
    headroom = 22
    limit = len(authored_visible_copy(page, [])) + headroom
    mock = completed_mock(monkeypatch, [first, second, third])
    revised = revise_descriptions(mock, page, {'context-0': 'Describe the change of share.',
        'context-1': 'Identify whose view this was.'}, source_pages=evidence, periods=[], limit=limit)
    assert revised.source_context[0].description == 'Reports a larger share of early orders.'
    assert revised.source_context[1].description == reusable
    assert revised.source_context[2] == page.source_context[2]
    assert len(authored_visible_copy(revised, [])) <= limit
    assert len(mock.client.calls) == 3
    data = json.loads(mock.client.calls[-1][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    items = data['addressed_descriptions']
    assert sum(item['max_net_growth_characters'] for item in items.values()) == headroom
    for index in (0, 1):
        item = items[f'context-{index}']
        assert item['original_characters'] == len(page.source_context[index].description)
        assert item['shorter_net_change_target'] < 0 < item['max_net_growth_characters']
        assert item['concise_net_change_target'] <= item['max_net_growth_characters']


def test_resumed_mixed_selection_preserves_existing_wording_among_equally_sparse_combinations():
    from adaptive_document_agent.agent.retained_description_revision import select_description_span_page
    from adaptive_document_agent.agent.retained_page_sources import authored_visible_copy

    page, _ = source_page()
    page.source_context[0].description = 'Reports earlier orders and the established purchasing terms and prior delivery conditions.'
    page.source_context[1].description = 'Describes the exposure that management reports for customer orders.'
    first, second = [item.description for item in page.source_context[:2]]
    sparse = {'context-0': [first + ' The company also considered timing.'],
              'context-1': [second + ' Management monitored the reported conditions.']}
    previous = {'context-0': ['Reports order timing.'], 'context-1': ['Describes exposure for customer orders.']}
    limit = len(authored_visible_copy(page, [])) + 20
    for sequence in (sparse, dict(reversed(list(sparse.items())))):
        revised = select_description_span_page(page, {'context-0': 0, 'context-1': 1}, sequence, previous,
                                               [], [], limit)
        assert revised.source_context[0].description == sparse['context-0'][0]
        assert revised.source_context[1].description == previous['context-1'][0]
        assert revised.source_context[2] == page.source_context[2]
        assert len(authored_visible_copy(revised, [])) <= limit


@pytest.mark.parametrize('case', ['success', 'no_match', 'source_invalid', 'malformed', 'joint_fails',
                                  'no_owner_issue', 'room_for_rewrite'])
def test_sparse_first_tight_owner_corrections_have_one_bounded_fallback(monkeypatch, case):
    from adaptive_document_agent.agent.retained_page_sources import authored_visible_copy

    page, evidence = source_page()
    original = page.model_dump()
    size = len(authored_visible_copy(page, []))
    limit = 2 * size if case == 'room_for_rewrite' else size + 5
    reason = None if case == 'no_owner_issue' else 'Clarify the stated timing and type of exposure.'
    purposes = {'context-0': 'The review describes earlier receipt of orders.',
                'context-1': 'The operator found limited exposure.'}
    edit = dict(before='earlier', after='early')
    if case in ('no_match', 'joint_fails'):
        edit = dict(before='unwritten terms', after='early')
    elif case == 'source_invalid':
        edit = dict(before='earlier', after='more than 40% of the')
    other = dict(before='the exposure', after='low exposure')
    spans = {'context-0': dict(concise=[edit], shorter=[edit]), 'context-1': dict(concise=[other], shorter=[other])}
    whole = {'context-0': 'Reports early orders.', 'context-1': 'Describes low exposure.'}
    starts_sparse = case not in ('no_owner_issue', 'room_for_rewrite')
    responses = [spans] if starts_sparse else [whole]
    if case in ('no_match', 'source_invalid'):
        responses.append(whole)
    elif case == 'malformed':
        del spans['context-1']
    elif case == 'joint_fails':
        responses.extend([{'context-0': 'Reports the order timing. ' * 32,
                           'context-1': 'Describes the limited exposure. ' * 9},
                          {slot: dict(concise='Invents an unbound 77%.', shorter='Reports an unbound 50%.')
                           for slot in purposes}])
    mock = completed_mock(monkeypatch, responses)
    if case in ('joint_fails', 'malformed'):
        with pytest.raises((ValueError, LLMStructuredOutputError)):
            revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=limit, owner_issue=reason)
    else:
        revised = revise_descriptions(mock, page, purposes, source_pages=evidence, periods=[], limit=limit, owner_issue=reason)
        assert revised.source_context[0].description == whole['context-0']
        assert revised.source_context[1].description == whole['context-1']
        assert revised.source_context[2] == page.source_context[2]
        assert revised.all_context_evidence == page.all_context_evidence and len(authored_visible_copy(revised, [])) <= limit
    operations = [call['operation'] for call in mock.usage]
    if starts_sparse:
        assert operations[0] == 'RetainedDescriptionSpanRepair' and operations.count('RetainedDescriptionSpanRepair') == 1
        data = json.loads(mock.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        assert data['owner_review_issue'] == reason
        assert set(data['addressed_descriptions']) == set(purposes)
        assert all('first_rewrite' not in item and 'unsuccessful_alternatives' not in item
                   for item in data['addressed_descriptions'].values())
        assert operations[1:] == (['RetainedDescriptionRevision', 'RetainedDescriptionLengthRepair']
            if case == 'joint_fails' else ['RetainedDescriptionRevision'] if case in ('no_match', 'source_invalid') else [])
    else:
        assert operations == ['RetainedDescriptionRevision']
    assert page.model_dump() == original
