import pytest

from adaptive_document_agent.agent.compact_summary import SummarySynthesisDraft
from adaptive_document_agent.agent.summary_content_repair import SummarySynthesisRevision, apply_content_revision


def draft():
    return SummarySynthesisDraft(name='Issuer', name_quote='Issuer', name_page=1, pages=[
        dict(placement='body', title='Business', items=[
            dict(label='Scope', text='The issuer develops and sells products.', fact_ids=['f0']),
            dict(label='Portfolio', text='Accessories and installed product volumes are retained.', fact_ids=['f1'])]),
        dict(placement='appendix', title='Market', items=[
            dict(label='Market position', text='The issuer leads its domestic market.', fact_ids=['f2'])])])


def test_attribution_repair_cannot_regenerate_other_accepted_paragraphs():
    original = draft()
    patch = SummarySynthesisRevision(replacements=[dict(page_index=1, item_index=0,
        replacement=dict(label='Market position', text='According to the cited report, the issuer leads its domestic market.',
                         fact_ids=['f2']))])
    revised = apply_content_revision(original, patch, SummarySynthesisDraft)
    assert revised.pages[0].model_dump() == original.pages[0].model_dump()
    assert revised.model_dump(exclude={'pages'}) == original.model_dump(exclude={'pages'})
    assert revised.pages[1].placement == original.pages[1].placement == 'appendix'
    assert 'cited report' in revised.pages[1].items[0].text
    assert 'cited report' not in original.pages[1].items[0].text


def test_revision_rejects_unknown_empty_and_repeated_noop_targets():
    original = draft()
    item = original.pages[0].items[0].model_dump()
    for patch in [dict(), dict(replacements=[dict(page_index=8, item_index=0, replacement=item)]),
                  dict(replacements=[dict(page_index=0, item_index=9, replacement=item)]),
                  dict(replacements=[dict(page_index=0, item_index=0, replacement=item)] * 2)]:
        with pytest.raises(ValueError):
            apply_content_revision(original, SummarySynthesisRevision(**patch), SummarySynthesisDraft)


@pytest.mark.parametrize('conflict', [None, 'text', 'facts', 'title'])
def test_identical_targeted_edits_are_idempotent_but_conflicts_fail(conflict):
    from copy import deepcopy
    original = draft()
    edit = dict(page_index=1, item_index=0, replacement=dict(label='Market position',
        text='The source report ranks the issuer first domestically.', fact_ids=['f2']))
    other = deepcopy(edit)
    titles = [dict(page_index=1, title='Market evidence')] * 2
    if conflict == 'text': other['replacement']['text'] = 'A different statement.'
    elif conflict == 'facts': other['replacement']['fact_ids'] = ['f3']
    elif conflict == 'title': titles = [titles[0], dict(page_index=1, title='Different title')]
    patch = SummarySynthesisRevision(replacements=[edit, other], titles=titles)
    if conflict:
        with pytest.raises(ValueError, match='conflicting'):
            apply_content_revision(original, patch, SummarySynthesisDraft)
    else:
        revised = apply_content_revision(original, patch, SummarySynthesisDraft)
        assert revised.pages[0] == original.pages[0]
        assert len(revised.pages[1].items) == len(original.pages[1].items)
        assert revised.pages[1].items[0].model_dump() == edit['replacement']
        assert revised.pages[1].title == 'Market evidence'


def test_omitted_source_part_can_be_added_without_changing_existing_evidence():
    original = draft()
    patch = SummarySynthesisRevision(additions=[dict(page_index=1, item=dict(
        label='Delivery conditions', text='Installation requires customer acceptance.', fact_ids=['f3']))])
    revised = apply_content_revision(original, patch, SummarySynthesisDraft)
    assert revised.pages[1].items[0] == original.pages[1].items[0]
    assert revised.pages[1].items[1].fact_ids == ['f3']


def test_model_repairs_use_explicit_addresses_and_exclude_rendered_page_context():
    import json
    from pydantic import ValidationError
    from adaptive_document_agent.agent.summary_content_repair import revise_content
    original = draft()
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert 'rendered_pages' not in payload and 'previous_draft' not in payload
            assert payload['editable_groups'][1]['items'][0]['item_id'] == 'g1_i0'
            assert payload['source_facts'] == [dict(id='f3', part_id='part3', label='Conditions',
                source_quote='Delivery requires customer acceptance.\nReported 7.1%.', source_pages=[12])]
            for target in ['g19_i0', 'g1_i9', 'compact_summary_1']:
                with pytest.raises(ValidationError):
                    schema(replacements=[dict(item_id=target, replacement=original.pages[0].items[0])])
            with pytest.raises(ValidationError):
                schema(additions=[dict(group_id='g0', item=original.pages[0].items[0])])
            return schema(additions=[dict(group_id='g1', item=dict(label='Conditions',
                text='Delivery requires customer acceptance.', fact_ids=['f3']))])
    source = dict(parts=[dict(id='part3', facts=[dict(id='f3', label='Conditions', quote_ref='q3')])],
                  source_quotes=[dict(id='q3', pages=[12],
                      text='Delivery requires customer acceptance.\nReported 7.1%.')])
    revised = revise_content(Client(), original, [], SummarySynthesisDraft, {}, source=source,
                             errors=['Include delivery conditions.'])
    assert revised.pages[0] == original.pages[0]
    assert revised.pages[1].items[0] == original.pages[1].items[0]
    assert revised.pages[1].items[1].fact_ids == ['f3']
