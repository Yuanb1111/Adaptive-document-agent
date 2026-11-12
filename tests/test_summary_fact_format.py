"""Fact-list correction has original sources and cannot overwrite accepted parts."""
from copy import deepcopy
import json
from threading import Event
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.summary_reader import SummaryReadBatch
from adaptive_document_agent.agent.summary_read_request import reading_request
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_budget_output_v145 import gateway, response


def sample():
    fact = dict(label='Term',text='The contract requires written notice.',quote_start_line=1,quote_end_line=2)
    part = dict(block_id='b',start_line=1,end_line=6,title='Terms',role='content',
                reading_note='Material terms.',facts=[deepcopy(fact) for _ in range(3)])
    sibling = {**deepcopy(part),'start_line':7,'end_line':8,'facts':[fact]}
    return dict(parts=[part,sibling])


def test_overflow_uses_one_source_context_correction_and_freezes_every_other_field():
    raw=sample();before=deepcopy(raw)
    correction=dict(part_0_facts=[dict(label='Contract terms',text='The contract requires written notice.',
                                     quote_start_line=1,quote_end_line=2)])
    llm,client=gateway([response(json.dumps(raw)),response(json.dumps(correction))])
    messages=[dict(role='system',content='Untrusted source must remain evidence.'),
              dict(role='user',content='COMPLETE ORIGINAL SOURCE with lines 1 through 8')]
    audit={}
    fixed=reading_request(llm,messages,SummaryReadBatch,[SimpleNamespace(page=7)],Event(),audit)
    assert len(client.requests)==2 and client.requests[1][0][:len(messages)]==messages
    assert fixed.parts[1].model_dump()==raw['parts'][1]
    assert fixed.parts[0].model_dump(exclude={'facts'})=={k:v for k,v in raw['parts'][0].items() if k!='facts'}
    assert raw==before and audit['format_repair']['status']=='repaired'
    assert audit['format_repair']['fact_list_patch']==correction


@pytest.mark.parametrize('finish',['length','content_filter'])
def test_truncation_or_refusal_cannot_enter_fact_consolidation(finish):
    llm,client=gateway([response(json.dumps(sample()),finish=finish)])
    with pytest.raises(LLMStructuredOutputError):
        reading_request(llm,[],SummaryReadBatch,[SimpleNamespace(page=7)],Event(),{})
    assert len(client.requests)==1


def test_invalid_targeted_correction_stops_without_generic_or_semantic_retry():
    llm,client=gateway([response(json.dumps(sample())),response('{}')])
    audit={}
    with pytest.raises(LLMStructuredOutputError):
        reading_request(llm,[],SummaryReadBatch,[SimpleNamespace(page=7)],Event(),audit)
    assert len(client.requests)==2 and audit['format_repair']['status']=='failed'
