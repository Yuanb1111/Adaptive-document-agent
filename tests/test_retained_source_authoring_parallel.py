"""Priority membership has one owner; page authors cannot alter that choice."""
import json
from threading import Barrier,Lock

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent import retained_source_authoring_parallel as module
from adaptive_document_agent.agent.retained_analysis import selection_context,selected_record
from adaptive_document_agent.agent.retained_page_sources import writer_context,source_row_assurance
from adaptive_document_agent.utils.record_encoding import decode_records
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway


def ready():
    result,_,selection=fixture()
    context=selection_context(result,source_authoring=True)
    packet,aliases=writer_context(context)
    packet['source_row_assurance']=source_row_assurance(result,aliases)
    messages=[dict(role='system',content='Original writer instructions.'),
        dict(role='user',content='Trusted user audience requirements.'),
        dict(role='user',content='Original untrusted packet.')]
    return result,selection,context,packet,aliases,messages


@pytest.mark.parametrize('failure',['unknown','duplicate','missing_reason','foreign_reason'])
def test_priority_schema_rejects_ambiguous_ids_and_incomplete_decisions(failure):
    _,_,_,packet,_,_=ready()
    schema=module.source_priority_schema(packet)
    iid=packet['findings'][0]['insight']['id']
    response=dict(ordered_insight_ids=[iid],reasons={iid:'Material source-backed comparison.'})
    if failure=='unknown':response['ordered_insight_ids']=['other']
    if failure=='duplicate':response['ordered_insight_ids']=[iid,iid]
    if failure=='missing_reason':response['reasons']={}
    if failure=='foreign_reason':response['reasons']['other']='Unowned reason.'
    with pytest.raises(ValidationError):schema.model_validate(response)


def test_source_choice_and_owned_page_keep_original_context_without_publication_approval():
    result,selection,context,packet,aliases,messages=ready()
    iid=selection.ordered_insight_ids[0]
    llm=gateway([dict(ordered_insight_ids=[iid],reasons={iid:'Source comparison.'}),
                 selection.decisions[0].page.model_dump(mode='json')])
    draft=module.select_owned_source_pages(llm,result,context,packet,aliases,messages,'Read full source.')
    assert draft.ordered_insight_ids==[iid] and draft.decisions[0].decision=='include'
    assert draft.decisions[0].page is not None and selected_record(result) is None
    assert [u['operation'] for u in llm.usage]==['SourcePrioritySelection','OwnedSourcePage']
    request=decode_records(json.loads(llm.client.calls[1][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
    assert request['source_pages']==packet['source_pages']
    assert request['owned_insight_id']==iid
    assert messages[1] in llm.client.calls[1]
    assert result.validation_warnings[-1].code=='retained_source_priorities'


@pytest.mark.parametrize('fails',[False,True])
def test_owned_authors_overlap_drain_failures_and_cannot_change_membership(monkeypatch,fails):
    result,_,context,packet,aliases,messages=ready()
    original=result.insights[0]
    second=original.model_copy(update={'id':'other'})
    result.insights.append(second)
    context['findings'].append({**context['findings'][0],'insight':second.model_dump(mode='json')})
    packet['findings'].append({**packet['findings'][0],'insight':second.model_dump(mode='json')})
    order=[original.id,second.id];barrier=Barrier(2);finished=[];lock=Lock()
    def request(gateway,wire,schema,current,attempt,**kwargs):
        if schema.__name__=='SourcePrioritySelection':
            return schema.model_validate(dict(ordered_insight_ids=order,
                reasons={iid:'Synthetic owner protocol check.' for iid in order}))
        payload=decode_records(json.loads(wire[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
        iid=payload['owned_insight_id']
        try:
            barrier.wait(timeout=10)
            assert payload['source_pages']==packet['source_pages']
            assert [f['insight']['id'] for f in payload['findings']]==[iid]
            assert payload['ordered_selection']==order
            if fails and iid=='other':raise RuntimeError('Source writer unavailable')
            return schema(title=iid,message='The source reports revenue.')
        finally:
            with lock:finished.append(iid)
    monkeypatch.setattr(module,'selection_request',request)
    if fails:
        with pytest.raises(RuntimeError):
            module.select_owned_source_pages(None,result,context,packet,aliases,messages,'Read source.')
    else:
        draft=module.select_owned_source_pages(None,result,context,packet,aliases,messages,'Read source.')
        assert draft.ordered_insight_ids==order
        assert all(d.page.title==d.insight_id for d in draft.decisions if d.decision=='include')
    assert set(finished)==set(order) and selected_record(result) is None
