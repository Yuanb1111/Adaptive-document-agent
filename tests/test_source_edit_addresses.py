from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from adaptive_document_agent.agent.retained_literal_proof_references import literal_proof_catalog
from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_compact_publication_copy import base_gateway, payload


def source_case():
    source = payload()
    texts = ['Drivers of the annual losses.', 'Original impairment test result.',
             'The impairment test assumptions.', 'The subsequent sale of inventory.']
    source['source_pages'] = [dict(page=i+2, text=t) for i, t in enumerate(texts)]
    refs = list(literal_proof_catalog(source['source_pages'])[0])
    source['pages_to_correct']['owned']['draft']['source_context'] = [
        dict(scope='annual results', description='Describes the original losses.', quote=source['source_pages'][0]),
        dict(scope='each reporting period', description='Describes the impairment test.', quote=source['source_pages'][1])]
    return source, refs


def source_reply(refs, *, one_based=False):
    change = dict(scope='each reporting period', description='Describes the impairment test assumptions.',
                  quote=dict(passage_id=refs[2]), continuation_quotes=[dict(passage_id=refs[1])])
    n = int(one_based)
    return dict(message=None, source_context=None, source_context_edits={
        f'context-{n}': 'Attributes the annual losses to investment.',
        f'context-{n+1}': change})


def test_complete_one_based_edit_set_binds_only_to_the_uniquely_located_originals():
    source, refs = source_case()
    original = deepcopy(source)
    reply = source_reply(refs, one_based=True)
    reply['source_context_additions'] = None
    seen = []
    # The two wire shapes must receive identical normal validation and output.
    for raw in (reply, source_reply(refs)):
        raw.update(companion_ids=['bound-row'], context_evidence=[])
        revised = compact_publication_copy(base_gateway([raw]), 'owned', source, 1500,
            lambda pages: seen.append(pages['owned']) or {}, preserve_inputs=False)['owned']
    assert len(seen) == 2 and seen[0] == seen[1] == revised
    assert [c.quote.page for c in revised.source_context] == [2, 4]
    assert [q.page for q in revised.source_context[1].continuation_quotes] == [3]
    assert source == original


@pytest.mark.parametrize('explicit_null', [False, True])
def test_named_additions_inside_canonical_edits_follow_normal_binding(explicit_null):
    source, refs = source_case()
    new = dict(scope='subsequent period', description='Reports the subsequent sale of inventory.',
               quote=dict(passage_id=refs[3]))
    nested = source_reply(refs)
    nested['source_context_edits']['source_context_additions'] = [new]
    if explicit_null:
        nested['source_context_additions'] = None
    canonical = source_reply(refs)
    canonical['source_context_additions'] = [new]
    pages = []
    for raw in (nested, canonical):
        raw.update(companion_ids=['bound-row'], context_evidence=[])
        pages.append(compact_publication_copy(base_gateway([raw]), 'owned', source, 1500,
            lambda _: {}, preserve_inputs=False)['owned'])
    assert pages[0] == pages[1]
    assert pages[0].source_context[-1].quote.text == source['source_pages'][3]['text']


@pytest.mark.parametrize('defect', ['duplicate_location', 'full_replacement', 'wrong_shape',
                                    'unknown_proof', 'extra_field', 'too_many', 'misspelled'])
def test_nested_additions_cannot_conflict_or_escape_normal_schema(defect):
    source, refs = source_case()
    addition = dict(scope='subsequent events', description='Reports the subsequent sale of inventory.',
                    quote=dict(passage_id=refs[3]))
    raw = source_reply(refs)
    edits = raw['source_context_edits']
    edits['source_context_additions'] = [addition]
    if defect == 'duplicate_location':
        raw['source_context_additions'] = [deepcopy(addition)]
    elif defect == 'full_replacement':
        raw['source_context'] = []
    elif defect == 'wrong_shape':
        edits['source_context_additions'] = addition
    elif defect == 'unknown_proof':
        addition['quote'] = dict(passage_id='unknown')
    elif defect == 'extra_field':
        addition['approved'] = True
    elif defect == 'too_many':
        edits['source_context_additions'] *= 9
    else:
        edits['additions'] = edits.pop('source_context_additions')
    raw.update(companion_ids=['bound-row'], context_evidence=[])
    with pytest.raises((LLMStructuredOutputError, AuthoredPageErrors)):
        compact_publication_copy(base_gateway([raw, raw]), 'owned', source, 1500,
            lambda _: pytest.fail('Invalid additions accepted'), preserve_inputs=False)


@pytest.mark.parametrize('defect', ['shared_proof', 'conflicting_scope', 'unanchored',
                                    'wrong_anchor', 'sparse', 'foreign_key'])
def test_a_number_outside_the_catalog_is_never_sufficient_to_rebind(defect):
    source, refs = source_case()
    raw = source_reply(refs, one_based=True)
    edits = raw['source_context_edits']
    if defect == 'shared_proof':
        source['pages_to_correct']['owned']['draft']['source_context'][0]['continuation_quotes'] = [
            source['source_pages'][1]]
    elif defect == 'conflicting_scope':
        edits['context-2']['scope'] = 'a different discussion'
    elif defect == 'unanchored':
        edits['context-2'] = 'Describes the separate discussion.'
    elif defect == 'wrong_anchor':
        edits['context-2']['continuation_quotes'] = [dict(passage_id=refs[0])]
    elif defect == 'sparse':
        del edits['context-1']
    else:
        edits['context-3'] = 'Describes an unrequested qualification.'
    raw.update(companion_ids=['bound-row'], context_evidence=[])
    with pytest.raises(LLMStructuredOutputError):
        compact_publication_copy(base_gateway([raw, raw]), 'owned', source, 1500,
            lambda _: pytest.fail('Unresolved slot alias accepted'), preserve_inputs=False)


@pytest.mark.parametrize('duplicate', ['source_context_additions', 'context-1'])
def test_duplicate_raw_edit_addresses_cannot_supply_a_candidate(duplicate):
    source, refs = source_case()
    raw = source_reply(refs, one_based=True)
    raw['source_context_edits']['source_context_additions'] = [{
        'scope': 'the subsequent period', 'description': 'Reports the subsequent inventory sale.',
        'quote': dict(passage_id=refs[3])}]
    raw.update(companion_ids=['bound-row'], context_evidence=[])
    first = json.dumps(raw)
    key = json.dumps(duplicate) + ':'
    first = first.replace(key, key + '[], ' + key, 1)
    with pytest.raises(LLMStructuredOutputError):
        compact_publication_copy(base_gateway([first, first]), 'owned', source, 1500,
            lambda _: pytest.fail('Conflicting addresses accepted'), preserve_inputs=False)
