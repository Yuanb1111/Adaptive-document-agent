"""An additional context slot must preserve both its existing copy and exact proof."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from adaptive_document_agent.agent.reported_source_context import group_adjacent_source_context
from adaptive_document_agent.utils.record_encoding import decode_records
from tests.test_compact_publication_copy import base_gateway, payload


def source_items():
    proof=dict(page=2,text='Literal source quotation.')
    tail=dict(page=2,text='The source discusses related additional conditions.')
    scopes=('assembly','delivery','sales','orders','staff','returns','products','support')
    original=[dict(scope=scope,description=f'Describes the evidence for {scope}.',quote=proof) for scope in scopes]
    original[6]['continuation_quotes']=[tail]
    original[7]={**original[6],'description':'Reports the related operating qualification.'}
    addition=dict(scope='settlement',description='Describes the reported subsequent event.',quote=proof)
    return original,addition


@pytest.mark.parametrize('as_addition',[False,True])
def test_page_replacement_and_addressed_addition_both_keep_identical_adjacent_ownership(as_addition):
    items,addition=source_items()
    source=payload()
    source['pages_to_correct']['owned']['draft']['source_context']=items
    original=deepcopy(source)
    response=(dict(message=None,source_context=None,source_context_additions=[addition]) if as_addition
              else dict(message=None,source_context=items+[addition]))
    llm=base_gateway([response])

    result=compact_publication_copy(llm,'owned',source,2000,lambda _: {})['owned']

    merged={**items[6],'description':items[6]['description']+' '+items[7]['description']}
    assert [c.model_dump() for c in result.source_context]==[*items[:6],merged,addition]
    assert source==original and len(llm.usage)==1
    wire=llm.client.calls[0][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]
    assert decode_records(json.loads(wire))['mergeable_existing_slots']==[['context-6','context-7']]


@pytest.mark.parametrize('difference',['scope','page','quote','continuation_order','nonadjacent','invalid'])
def test_grouping_requires_exact_ordered_ownership_and_valid_paragraphs(difference):
    items,addition=source_items()
    items[6]['continuation_quotes']=[*items[6]['continuation_quotes'],dict(page=2,text='The next source.')]
    items[7]=deepcopy(items[6])
    if difference=='scope': items[7]['scope']+=' update'
    if difference=='page': items[7]['quote']['page']=3
    if difference=='quote': items[7]['quote']['text']+=' update'
    if difference=='continuation_order': items[7]['continuation_quotes'].reverse()
    if difference=='invalid': items[7]['description']=''
    if difference=='nonadjacent': items.insert(7,addition)
    else: items.append(addition)
    assert group_adjacent_source_context(items) is items


def test_overlong_group_reuses_only_its_own_capacity_slot(monkeypatch):
    items,addition=source_items()
    source=payload()
    source['source_pages'][0]['text']+=' '+items[6]['continuation_quotes'][0]['text']
    for index,subject in ((6,'product qualification'),(7,'related condition')):
        items[index]['description']='Describes '+(subject+' ')*20+'.'
    joined=items[6]['description']+' '+items[7]['description']
    assert len(joined)>700
    compact='Describes the product qualification and the related condition.'
    llm=base_gateway([dict(message=None,source_context=items+[addition]),dict(context_7=[compact])])
    generate=llm.client.generate_text
    def stopped(*args,**kwargs):
        result=generate(*args,**kwargs)
        result.usage.finish_reason='stop'
        return result
    monkeypatch.setattr(llm.client,'generate_text',stopped)

    result=compact_publication_copy(llm,'owned',source,1500,lambda _: {})['owned']

    assert [c.model_dump() for c in result.source_context]==[*items[:6],{**items[6],'description':compact},addition]
    assert [row['operation'] for row in llm.usage]==['RetainedPageRevisions','RetainedSourceDescriptionCapacity']
    assert joined in str(llm.client.calls[1])
