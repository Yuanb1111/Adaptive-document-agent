"""Missing source qualifications can be appended without rewriting accepted copy."""
import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.retained_page_revision import RetainedPageRevisions, merge_page_revisions


def original():
    return {'finding': dict(page=dict(title='Reported measure', message='The original source-supported sentence.',
        companion_ids=['row-1'], context_evidence=[]))}


def test_append_keeps_original_sentences_values_and_bindings_literal():
    decisions = original()
    patch = RetainedPageRevisions(edits={'finding': dict(message_append=[
        'The source gives a later period-specific qualification.'])})
    result = merge_page_revisions(patch, decisions, {'finding'})['finding']
    assert result.message == decisions['finding']['page']['message'] + ' The source gives a later period-specific qualification.'
    assert result.companion_ids == ['row-1'] and result.context_evidence == []
    assert decisions == original()


def test_append_can_accompany_an_independent_literal_correction():
    patch = RetainedPageRevisions(edits={'finding': dict(title=[dict(span_id='copy-0', after='Source measure')],
        message_append=['A source-supported limitation applies.'])})
    page = merge_page_revisions(patch, original(), {'finding'})['finding']
    assert page.title == 'Source measure'
    assert page.message.startswith(original()['finding']['page']['message'])


def test_append_does_not_expand_the_merged_page_capacity():
    decisions = original()
    decisions['finding']['page']['message'] = 'A' * 1950
    patch = RetainedPageRevisions(edits={'finding': dict(message_append=['B' * 100])})
    with pytest.raises(ValidationError):
        merge_page_revisions(patch, decisions, {'finding'})


def test_multisentence_append_uses_the_complete_page_limit():
    paragraph = 'A source-supported qualification. ' * 20
    assert len(paragraph) > 500
    patch = RetainedPageRevisions(edits={'finding': dict(message_append=[paragraph])})
    page = merge_page_revisions(patch, original(), {'finding'})['finding']
    assert page.message == original()['finding']['page']['message'] + ' ' + paragraph
