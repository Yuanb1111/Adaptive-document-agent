"""A writer owns the choice between materially different complete and sparse candidates."""
import json

from adaptive_document_agent.agent.retained_page_revision import PublishedPageRevisions, merge_page_revisions
from adaptive_document_agent.agent.retained_revision_choices import choose_revision_candidates
from tests.test_retained_analysis_v216 import gateway


def page(message='Original source statement. Copied explanation.'):
    return dict(title='Working capital', message=message, source_context=[dict(scope='liquidity',
        description='describes timing of customer payments', quote=dict(page=8, text='Payments arrived later.'))])


def choose(llm, value, current, published):
    return choose_revision_candidates(llm, value, PublishedPageRevisions, current, current.keys(), published,
                                      {key: ['Clarify the supported explanation.'] for key in current}, lambda *_: [])


def test_equal_full_and_sparse_outputs_need_no_model_choice():
    current = {'owner': {'page': page()}}
    value = dict(pages={'owner': page('Edited. Copied explanation.')}, edits={'owner': {
        'message': [{'span_id': 'copy-0', 'after': 'Edited.'}]}})
    llm = gateway([])
    revision, pending = choose(llm, value, current, {})
    result = merge_page_revisions(revision, current, current.keys())['owner']
    assert result.message == 'Edited. Copied explanation.' and not pending and not llm.usage


def test_mixed_owners_must_choose_and_can_keep_provenanced_slot_while_removing_duplicate():
    current = {'first': {'page': page()}, 'second': {'page': page()}}
    value = dict(pages={'second': page('Full candidate.')}, edits={
        'first': {'message': [{'span_id': 'copy-1', 'after': ''}],
                  'source_context_descriptions': {'context-0': 'Overlong source. ' * 60}},
        'second': {'message': [{'span_id': 'copy-0', 'after': 'Alternative candidate.'}]}})
    published = {'first': {'context-0': 'For liquidity, the source describes timing of customer payments.'}}
    llm = gateway([{'first': 'keep_published_description', 'second': 'full_page'}])
    revision, pending = choose(llm, value, current, published)
    pages = merge_page_revisions(revision, current, current.keys(), published_descriptions=published)
    assert not pending and [r['operation'] for r in llm.usage] == ['RetainedRevisionChoices']
    assert pages['first'].message.strip() == 'Original source statement.' and pages['second'].message == 'Full candidate.'
    assert pages['first'].source_context[0].model_dump() == page()['source_context'][0]
    packet = json.loads(llm.client.calls[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(packet['second']['choices']) == {'span_edits', 'full_page'}
    assert set(packet['first']['choices']) == {'keep_published_description'}


def test_choice_can_request_rewrite_and_valid_sibling_stays_frozen():
    current = {'ambiguous': {'page': page()}, 'good': {'page': page()}}
    value = dict(pages={'ambiguous': page('Complete version.')}, edits={
        'ambiguous': {'message': [{'span_id': 'copy-0', 'after': 'Different sparse change.'}]},
        'good': {'message': [{'span_id': 'copy-0', 'after': 'Corrected.'}]}})
    llm = gateway([{'ambiguous': 'rewrite'}])
    revision, pending = choose(llm, value, current, {})
    assert set(pending) == {'ambiguous'}
    pages = merge_page_revisions(revision, current, current.keys())
    assert pages['good'].message == 'Corrected. Copied explanation.' and pages['ambiguous'].message == page()['message']


def test_overlong_answer_without_other_valid_edits_needs_rewrite_not_implicit_acceptance():
    current = {'owner': {'page': page()}}
    value = dict(edits={'owner': {'source_context_descriptions': {'context-0': 'x' * 701}}})
    llm = gateway([])
    _, pending = choose(llm, value, current, {'owner': {'context-0': 'Published explanation'}})
    assert set(pending) == {'owner'} and not llm.usage
