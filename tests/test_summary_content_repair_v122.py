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


def test_revision_rejects_duplicate_unknown_and_empty_targets():
    original = draft()
    item = original.pages[0].items[0].model_dump()
    for patch in [dict(), dict(replacements=[dict(page_index=8, item_index=0, replacement=item)]),
                  dict(replacements=[dict(page_index=0, item_index=9, replacement=item)]),
                  dict(replacements=[dict(page_index=0, item_index=0, replacement=item)] * 2)]:
        with pytest.raises(ValueError):
            apply_content_revision(original, SummarySynthesisRevision(**patch), SummarySynthesisDraft)


def test_omitted_source_part_can_be_added_without_changing_existing_evidence():
    original = draft()
    patch = SummarySynthesisRevision(additions=[dict(page_index=1, item=dict(
        label='Delivery conditions', text='Installation requires customer acceptance.', fact_ids=['f3']))])
    revised = apply_content_revision(original, patch, SummarySynthesisDraft)
    assert revised.pages[1].items[0] == original.pages[1].items[0]
    assert revised.pages[1].items[1].fact_ids == ['f3']
