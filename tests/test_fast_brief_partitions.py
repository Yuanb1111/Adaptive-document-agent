"""Parallel literal verdicts and mixed patch transports retain strict ownership."""
from copy import deepcopy
import json
from threading import Barrier, Event, Lock, get_ident
from types import SimpleNamespace

from pydantic import BaseModel,ConfigDict,create_model
import pytest

from adaptive_document_agent.agent import brief_literal_partitions as literal
from adaptive_document_agent.agent.brief_patch_partitions import generate_patch
from adaptive_document_agent.agent.brief_quantity_references import NativeQuantityBriefItem
from adaptive_document_agent.agent.brief_evidence_blocks import ReferencedBriefItem
from adaptive_document_agent.agent.brief_review_progress import brief_progress,report_brief_progress
from adaptive_document_agent.agent.brief_review_checkpoint import BriefReviewUnavailable
from adaptive_document_agent.services.llm.config import LLMSettings


class Verdict(BaseModel):
    index:int


class Verdicts(BaseModel):
    items:list[Verdict]


def payload(messages):
    return json.loads(messages[1]['content'].split('\n',1)[1].rsplit('\n',1)[0])


def test_literal_requests_overlap_but_verdicts_and_progress_are_attached_on_caller(monkeypatch):
    caller=get_ident();barrier=Barrier(3);threads=[];progress=[]
    rows=[dict(index=i,quotes=[dict(raw='-12.00',unit='source unit',period='FY2025')]) for i in (1,4,7)]
    before=deepcopy(rows)
    def request(gateway,messages,schema,record,limits,label,cancelled):
        threads.append(get_ident());scoped=payload(messages)
        assert len(scoped)==1 and scoped[0] in rows
        report_brief_progress('Independent source check started')
        barrier.wait(5)
        return Verdicts(items=[Verdict(index=scoped[0]['index'])])
    monkeypatch.setattr(literal,'_request',request)
    with brief_progress(lambda text:progress.append((get_ident(),text))):
        responses=[]
        for response,owned,messages in literal.literal_partitions(SimpleNamespace(discovery_workers=8),
                [dict(role='system',content='Own-source checks only.')],Verdicts,rows,{}):
            assert get_ident()==caller and owned==payload(messages)
            responses.extend(v.index for v in response.items)
    assert set(responses)=={1,4,7} and len(set(threads))==3 and caller not in threads
    assert progress and {i for i,_ in progress}=={caller} and rows==before


def test_failed_literal_partition_preserves_successes_but_never_approves_the_whole(monkeypatch):
    def request(gateway,messages,schema,*args):
        row=payload(messages)[0]
        if row['index']==1:raise BriefReviewUnavailable({1:'unavailable'})
        return Verdicts(items=[Verdict(index=row['index'])])
    monkeypatch.setattr(literal,'_request',request)
    checked=[]
    with pytest.raises(BriefReviewUnavailable) as failed:
        for response,_,_ in literal.literal_partitions(SimpleNamespace(discovery_workers=8),
                [dict(role='system',content='Source only')],Verdicts,[dict(index=i) for i in (1,2)],{}):
            checked.extend(v.index for v in response.items)
    assert checked==[2] and failed.value.failures=={1:'unavailable'}


def test_two_mixed_patch_types_have_separate_schemas_and_no_borrowed_quantity_ids():
    schema=create_model('ExecutiveBriefPatch',__config__=ConfigDict(extra='forbid'),
        item_0=(NativeQuantityBriefItem,...),item_1=(ReferencedBriefItem,...))
    barrier=Barrier(2);calls=[]
    context=dict(invalid_items={f'item_{i}':dict(label='Source',text='Original source claim.') for i in (0,1)},
        source_quantity_reference_options={'item_0':{'q0':'USD 12 million'}},validation_errors={})
    class Gateway:
        discovery_workers=8
        def generate_structured(self,messages,schema,**kwargs):
            key,=schema.model_fields
            scoped=json.loads(messages[-2]['content'].split('\n',1)[1].rsplit('\n',1)[0])
            calls.append(key);assert set(scoped['invalid_items'])=={key}
            expected={'item_0':{'q0':'USD 12 million'}} if key=='item_0' else {}
            assert scoped['source_quantity_reference_options']==expected
            barrier.wait(5)
            return schema.model_validate({key:dict(label='Source',text=['Value was ',dict(quantity_ref='q0')]
                if key=='item_0' else 'The source qualifies this finding.',evidence=[dict(ref='p1_b1')])})
    original=deepcopy(context)
    response=generate_patch(Gateway(),[dict(role='system',content='Source only'),dict(role='user',content='context')],
                            schema,context,{})
    assert set(calls)=={'item_0','item_1'} and context==original
    assert isinstance(response.item_0.text,list) and isinstance(response.item_1.text,str)


def test_initial_brief_capacity_is_explicit_and_bounded():
    assert LLMSettings().brief_initial_findings==7
    assert LLMSettings(brief_initial_findings=3).brief_initial_findings==3
    for invalid in (0,2,8):
        with pytest.raises(ValueError):LLMSettings(brief_initial_findings=invalid)


@pytest.mark.parametrize('context_reject',[False,True])
def test_integrated_fast_review_keeps_whole_context_gate_and_exact_owned_verdicts(context_reject):
    from tests.test_brief_context_review_v215 import large_fixture,ReviewGateway
    from tests.test_brief_meaning_capacity_v213 import payload as request_payload
    from tests.test_brief_review_checkpoint_v215 import latest
    from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
    brief,result,context=large_fixture();before=deepcopy((brief,context,result.document))
    class FastGateway(ReviewGateway):
        def generate_structured(self,messages,schema,**kwargs):
            if schema.__name__=='BriefClaimDirectionReview':
                self.calls.append((schema.__name__,deepcopy(messages),get_ident()))
                return schema(items=[dict(index=row['index'],comparisons=[]) for row in request_payload(messages)])
            return super().generate_structured(messages,schema,**kwargs)
    llm=FastGateway(workers=8,context_reject=context_reject);llm.barrier=None
    errors=meaning_validator(llm,result=result,source_context=context)(brief)
    assert set(errors)==(set(range(5)) if context_reject else set())
    assert latest(result)['semantic_approval'] is (not context_reject)
    claims=[request_payload(messages) for name,messages,_ in llm.calls if name=='BriefMeaningReview']
    broad=[request_payload(messages) for name,messages,_ in llm.calls if name=='BriefContextReview']
    assert len(claims)==5 and all(len(rows)==1 for rows in claims) and len(broad)==1
    assert broad[0][0]['available_report_context']['evidence_blocks']==context['evidence_blocks']
    assert {rows[0]['index'] for rows in claims}==set(range(5))
    assert all('available_report_context' not in rows[0] for rows in claims)
    assert (brief,context,result.document)==before
