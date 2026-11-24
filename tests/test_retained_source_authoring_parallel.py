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


def test_owned_page_author_can_cite_the_exact_original_list_without_retyping_it():
    from adaptive_document_agent.agent.retained_literal_proof_references import literal_proof_catalog
    source = 'Adjusted for (1) non-cash charges and (2) movements in working capital.'
    continuation = 'The two adjustments are discussed separately below.'
    passages, rows = literal_proof_catalog([dict(page=34, text=source+'\n\n'+continuation)])
    refs = [dict(passage_id=row['passage_id']) for row in rows]
    schema = module.owned_page_schema(passages)
    raw = dict(title='Cash flow', message='The source explains the cash outflows.',
               context_evidence=[refs[1]], source_context=[dict(scope='the cash flow discussion',
               description='Attributes the adjustment to non-cash charges and movements in working capital.',
               quote=refs[0], continuation_quotes=[refs[1]])])
    page = schema.model_validate(raw)
    assert page.source_context[0].quote.text == source
    assert page.source_context[0].quote.page == 34
    assert page.source_context[0].continuation_quotes[0].text == continuation
    assert page.context_evidence[0].text == continuation
    assert 'passage_id' not in page.model_dump_json()
    for bad in [{'passage_id': 'absent'}, {**refs[0], 'page': 999}]:
        with pytest.raises(ValidationError):
            schema.model_validate({**raw, 'context_evidence': [bad]})


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
    assert request['selection_reading_guide']=='Source comparison.'
    assert messages[1] in llm.client.calls[1]
    assert result.validation_warnings[-1].code=='retained_source_priorities'
    audit=json.loads(result.validation_warnings[-1].message)
    assert audit['finding_references']=={'finding-1':iid}
    assert packet==before
    choice=decode_records(json.loads(llm.client.calls[0][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
    assert choice['findings'][0]['insight']['id']=='finding-1'
    assert choice['source_pages']==packet['source_pages']


def test_related_discussion_outside_the_table_window_reaches_only_its_page_writer():
    result,selection,context,packet,aliases,messages=ready()
    table_page=packet['source_pages'][0]['page']
    related_page=table_page+12
    packet['source_pages'].append({**packet['source_pages'][0],'page':related_page})
    iid=selection.ordered_insight_ids[0]
    priority=dict(ordered_insight_ids=['finding-1'],reasons={'finding-1':'Distinct source-backed finding.'},
                  related_reading_pages={'finding-1':[related_page,related_page+1],'other-finding':[table_page]})
    llm=gateway([priority,selection.decisions[0].page.model_dump(mode='json')])
    module.select_owned_source_pages(llm,result,context,packet,aliases,messages,'Read full source.')
    request=decode_records(json.loads(llm.client.calls[1][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
    assert {table_page,related_page}<=set(request['source_reading_pages'])
    assert related_page+1 not in request['source_reading_pages']
    assert request['source_pages']==packet['source_pages']
    audit=json.loads(result.validation_warnings[-1].message)
    assert audit['related_reading_pages']=={iid:[related_page]}
    assert audit['unavailable_reading_pages']=={iid:[related_page+1]}
    assert audit['unassigned_reading_hints']=={'other-finding':[table_page]}
    assert audit['final_presentation_approval'] is False
    schema=module.source_priority_schema(packet)
    with pytest.raises(ValidationError):
        schema.model_validate(dict(ordered_insight_ids=[iid],reasons={iid:'Included.'},
                                   related_reading_pages={iid:[-1]}))


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
    order=[original.id,second.id];barrier=Barrier(2);finished=[];wire_payloads=[];lock=Lock()
    def request(gateway,wire,schema,current,attempt,**kwargs):
        if schema.__name__=='SourcePrioritySelection':
            return schema.model_validate(dict(ordered_insight_ids=['finding-1','finding-2'],
                reasons={ref:'Synthetic owner protocol check.' for ref in ['finding-1','finding-2']}))
        serialized=wire[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]
        with lock:wire_payloads.append(serialized)
        payload=decode_records(json.loads(serialized))
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
    assert len(wire_payloads)==2
    from adaptive_document_agent.utils.record_encoding import encode_records
    source_json=json.dumps(encode_records(packet['source_pages']),ensure_ascii=False,separators=(',',':'))
    stable_prefix='{"source_pages":'+source_json+','
    assert all(serialized.startswith(stable_prefix) for serialized in wire_payloads)
    assert decode_records(json.loads(wire_payloads[0]))['source_pages']==packet['source_pages']
    assert decode_records(json.loads(wire_payloads[1]))['source_pages']==packet['source_pages']
    assert wire_payloads[0]!=wire_payloads[1]
