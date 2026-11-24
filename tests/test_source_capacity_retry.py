"""An unambiguous owned copy overflow can reuse a remaining correction round."""
import json

import pytest

from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from adaptive_document_agent.agent.retained_page_revision_parallel import (
    complete_owned_copy_revisions, revise_owned_pages,
)
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_compact_publication_copy import base_gateway, payload


def capacity_gateway(monkeypatch,second,finish='stop'):
    source=payload()
    proof=dict(page=2,text=source['source_pages'][0]['text'])
    candidate=dict(message='The source reports levels.',source_context=[dict(
        scope='the reported discussion',description='Describes '+('the source qualification; '*20),quote=proof)])
    llm=base_gateway([candidate,second])
    generate=llm.client.generate_text

    def reply(*args,**kwargs):
        response=generate(*args,**kwargs)
        response.usage.finish_reason=finish if len(llm.client.calls)==2 else 'stop'
        return response

    monkeypatch.setattr(llm.client,'generate_text',reply)
    return llm,source


@pytest.mark.parametrize('invalid,location',[
    (['Describes '+'a lengthy claim '*80],'context_1.0'),
    (['Describes the reported condition.']*9,'context_1'),
])
def test_capacity_overflow_retries_only_the_failed_page(monkeypatch,invalid,location):
    llm,source=capacity_gateway(monkeypatch,{'context_1':invalid})
    calls=[]

    def revise(pending,attempts):
        def single(own):
            iid,=own
            calls.append(iid)
            if iid=='sibling':
                return {iid:'Source-checked candidate'}
            if attempts:
                assert list(attempts)==[iid]
                assert attempts[iid][0].page.source_context[0].quote.page==2
                assert any('visible-copy budget' in msg for msg in attempts[iid][0].errors)
                assert any(f'capacity at {location}:' in msg for msg in own[iid])
                llm.client.responses.append(dict(message='The source reports levels.',source_context=[]))
            return compact_publication_copy(llm,iid,source,400,lambda _: {})
        return revise_owned_pages(pending,single)

    pages,remaining=complete_owned_copy_revisions({'owned':['Shorten copy'],'sibling':[]},2,revise)
    assert calls.count('sibling')==1 and calls.count('owned')==2
    assert remaining==0 and len(llm.usage)==3
    assert pages['owned'].source_context==[]


@pytest.mark.parametrize('kind',['refusal','truncated','missing','unexpected','duplicate','trailing',
                                 'malformed','wrong_item','too_short'])
def test_incomplete_or_ambiguous_capacity_output_is_fatal(monkeypatch,kind):
    long='a'*701
    raw=json.dumps({'context_1':[long]})
    response={
        'refusal':raw,'truncated':raw,'missing':{},'unexpected':{'context_1':[long],'context_2':[long]},
        'duplicate':'{"context_1":["old claim"],'+raw[1:],'trailing':raw+' extra',
        'malformed':raw[:-1],'wrong_item':{'context_1':['Describes the condition.']*9+[True]},
        'too_short':{'context_1':['a']},
    }[kind]
    finish={'refusal':'content_filter','truncated':'length'}.get(kind,'stop')
    llm,source=capacity_gateway(monkeypatch,response,finish)
    with pytest.raises(LLMStructuredOutputError):
        complete_owned_copy_revisions({'owned':['Shorten copy']},2,lambda issues,attempts:
            compact_publication_copy(llm,'owned',source,400,lambda _: {}))
    assert len(llm.usage)==2
