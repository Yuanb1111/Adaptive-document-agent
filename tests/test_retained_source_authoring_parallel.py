"""Priority membership has one owner; page authors cannot alter that choice."""
import json
from copy import deepcopy
from threading import Barrier,Lock

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent import retained_source_authoring_parallel as module
from adaptive_document_agent.agent.retained_analysis import selection_context,selected_record
from adaptive_document_agent.agent.retained_page_sources import writer_context,source_row_assurance
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
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
    before=deepcopy(packet)
    iid=selection.ordered_insight_ids[0]
    llm=gateway([dict(ordered_insight_ids=['finding-1'],reasons={'finding-1':'Source comparison.'}),
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
    audit=json.loads(result.validation_warnings[-1].message)
    assert audit['finding_references']=={'finding-1':iid}
    assert packet==before
    choice=decode_records(json.loads(llm.client.calls[0][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
    assert choice['findings'][0]['insight']['id']=='finding-1'
    assert choice['source_pages']==packet['source_pages']


@pytest.mark.parametrize('case',['missing','changes_order','missing_again','foreign_id','duplicate_key'])
def test_priority_missing_reason_uses_one_owned_repair_without_changing_existing_decisions(monkeypatch,case):
    result,_,_,packet,_,messages=ready()
    packet['findings']=[{**packet['findings'][0],'insight':{'id':ref}}
                        for ref in [f'finding-{index}' for index in range(1,21)]]
    schema=module.source_priority_schema(packet)
    original=dict(ordered_insight_ids=['finding-20'],reasons={f'finding-{index}':
        f'Omit redundant comparison {index}.' for index in range(1,20)})
    patch={'finding-20':'Include the distinct source-backed finding.'}
    if case=='changes_order':patch['ordered_insight_ids']=['finding-1']
    if case=='missing_again':patch={}
    if case=='foreign_id':original['ordered_insight_ids']=['foreign']
    if case=='duplicate_key':
        original='{"ordered_insight_ids":["finding-1"],"ordered_insight_ids":["finding-2"],"reasons":{"finding-1":"Omit."}}'
    llm=gateway([original,patch])
    base=llm.client.generate_text

    def with_complete_response(*args,**kwargs):
        response=base(*args,**kwargs)
        response.usage.finish_reason='stop'
        return response

    monkeypatch.setattr(llm.client,'generate_text',with_complete_response)

    def request():
        return module.selection_request(llm,messages,schema,result,0,repair_missing=lambda failure:
            module.repair_missing_priority_reasons(llm,messages,schema,failure))

    if case=='missing':
        repaired=request()
        assert repaired.ordered_insight_ids==original['ordered_insight_ids']
        assert repaired.reasons.model_dump(by_alias=True)=={**original['reasons'],**patch}
        assert json.loads(result.validation_warnings[-1].message)['repair_kind']=='owned_missing_fields'
        assert messages[-1] in llm.client.calls[1]
    else:
        with pytest.raises(LLMResponseError,match='response'):
            request()
    assert len(llm.client.calls)==2
    expected='SourcePrioritySelection' if case in {'foreign_id','duplicate_key'} else 'SourcePriorityMissingReasons'
    assert llm.usage[-1]['operation']==expected


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
            return schema.model_validate(dict(ordered_insight_ids=['finding-1','finding-2'],
                reasons={ref:'Synthetic owner protocol check.' for ref in ['finding-1','finding-2']}))
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
