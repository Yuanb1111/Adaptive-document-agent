"""A misplaced edit proof needs one exact, already established owner."""
import pytest

from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from adaptive_document_agent.agent.retained_literal_proof_references import literal_proof_catalog
from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_compact_publication_copy import payload
from tests.test_retained_analysis_v216 import gateway


def proof_fixture():
    source = payload()
    current = source['source_pages'][0]
    other = dict(page=3, text='The source describes a distinct operating condition.')
    source['source_pages'].append(other)
    one, two = literal_proof_catalog(source['source_pages'])[0]
    entries = [
        dict(scope='the first discussion', description='Reports the original first condition.', quote=current),
        dict(scope='the other discussion', description='Reports the original other condition.', quote=other)]
    draft = source['pages_to_correct']['owned']['draft']
    draft['source_context'] = entries
    edits = {'context-0':'Reports the revised first condition.',
             'context-1':'Reports the revised other condition.', 'quote':dict(passage_id=one)}
    response = dict(message=None, source_context=None, source_context_edits=edits)
    return source, entries, edits, response, one, two


@pytest.mark.parametrize('style', ['description', 'scope', 'complete'])
def test_unique_already_owned_primary_proof_is_retained_in_its_edited_slot(style):
    source, entries, edits, response, first, _ = proof_fixture()
    if style != 'description':
        edits['context-0'] = dict(scope=entries[0]['scope'], description='Reports the revised first condition.')
    if style == 'complete':
        edits['context-0']['quote'] = dict(passage_id=first)
    llm = gateway([response])
    page = compact_publication_copy(llm, 'owned', source, 1300, lambda _: {})['owned']
    assert len(llm.client.calls) == 1
    assert [i.quote.model_dump() for i in page.source_context] == [entry['quote'] for entry in entries]
    assert [i.description for i in page.source_context] == [
        'Reports the revised first condition.', 'Reports the revised other condition.']


@pytest.mark.parametrize('defect', ['shared', 'unaddressed', 'continuation_only', 'replaced'])
def test_ambiguous_valid_passage_returns_addressed_feedback_without_guessing(monkeypatch, defect):
    source, entries, edits, response, first, second = proof_fixture()
    if defect == 'shared':
        entries[1]['continuation_quotes'] = [entries[0]['quote']]
    elif defect == 'unaddressed':
        del edits['context-0']
    elif defect == 'continuation_only':
        entries[0]['continuation_quotes'] = [entries[0]['quote']]
        entries[0]['quote'] = entries[1]['quote']
    else:
        edits['context-0'] = dict(scope=entries[0]['scope'], description='Reports the revised first condition.',
                                  quote=dict(passage_id=second))
    draft = source['pages_to_correct']['owned']['draft']
    response.update(companion_ids=draft['companion_ids'],context_evidence=draft['context_evidence'])
    llm = gateway([response,response])
    generate = llm.client.generate_text
    def stopped(*args, **kwargs):
        response = generate(*args, **kwargs)
        response.usage.finish_reason = 'stop'
        return response
    monkeypatch.setattr(llm.client, 'generate_text', stopped)
    with pytest.raises(AuthoredPageErrors) as error:
        compact_publication_copy(llm, 'owned', source, 1300, lambda _: pytest.fail('Ambiguous proof accepted'),
                                 preserve_inputs=False)
    assert len(llm.usage) == 2
    message, = error.value.by_insight['owned']
    assert first in message and 'physical page 2' in message
    assert 'Allowed edit keys: context-0, context-1' in message
    assert first in llm.client.calls[1][-2]['content']


@pytest.mark.parametrize('bad', [{'passage_id':'unknown'}, {'text':'Free floating literal.'}])
def test_unowned_echo_does_not_grant_authority_to_arbitrary_source_metadata(bad):
    source, _, edits, response, _, _ = proof_fixture()
    edits['quote'] = bad
    with pytest.raises(LLMStructuredOutputError):
        compact_publication_copy(gateway([response,response]), 'owned', source, 1300,
                                 lambda _: pytest.fail('Malformed proof accepted'))
