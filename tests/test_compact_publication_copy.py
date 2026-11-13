"""Whole-copy replacement enforces capacity without truncating source evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_retained_analysis_v216 import gateway as base_gateway


def gateway(responses):
    return base_gateway([dict(response,source_context=response.get('source_context',[]))
                         for response in responses])


def payload():
    return dict(pages_to_correct={'owned':dict(draft=dict(title='Source',message='Original paragraph.',
        companion_ids=['bound-row'],context_evidence=[dict(page=2,text='Literal source quotation.')]),
        errors=['Retain the limiting source context.'])},source_pages=[dict(page=2,text='Literal source quotation.')])


def test_whole_paragraph_keeps_original_fields_and_requires_caller_validation():
    source=payload();before=deepcopy(source);checked=[]
    llm=gateway([dict(message='A concise source-supported paragraph.')])
    replacement=compact_publication_copy(llm,'owned',source,400,
        lambda pages: checked.append(pages) or {})['owned']
    assert replacement.companion_ids==['bound-row']
    assert replacement.context_evidence[0].text=='Literal source quotation.'
    assert checked and len(llm.usage)==1 and source==before


def test_only_exact_bound_calendar_spellings_normalize_before_capacity_validation():
    source=payload()
    source['pages_to_correct']['owned']['primary_observations']=[dict(period='2024-06-30')]
    llm=gateway([dict(message='As of June 30, 2024.')])
    # Canonical spelling fits; its literal calendar identity is unchanged.
    assert compact_publication_copy(llm,'owned',source,18,lambda _: {})['owned'].message=='As of 2024-06-30.'
    llm=gateway([dict(message='As of June 29, 2024.')]*2)
    with pytest.raises(LLMStructuredOutputError):
        compact_publication_copy(llm,'owned',source,18,lambda _: {})


@pytest.mark.parametrize('corrects',[True,False])
def test_complete_overlong_output_gets_only_one_source_aware_capacity_correction(corrects):
    llm=gateway([dict(message='A'*450),dict(message='Concise.' if corrects else 'A'*450)])
    if corrects:
        assert compact_publication_copy(llm,'owned',payload(),400,lambda _: {})['owned'].message=='Concise.'
    else:
        with pytest.raises(LLMStructuredOutputError):
            compact_publication_copy(llm,'owned',payload(),400,lambda _: {})
    assert len(llm.client.calls)==2
    assert 'single existing source/length contract correction' in str(llm.client.calls[1])
    assert all(row['operation']=='RetainedPageRevisions' for row in llm.usage)


@pytest.mark.parametrize('defect',['rows','quotes','source'])
def test_source_failure_or_removed_evidence_cannot_be_published(defect):
    response=dict(message='A short paragraph.')
    if defect=='rows': response['companion_ids']=[]
    if defect=='quotes': response['context_evidence']=[]
    llm=gateway([response,response])
    validate=lambda _: {'owned':['Unsupported number.']} if defect=='source' else {}
    with pytest.raises(AuthoredPageErrors):
        compact_publication_copy(llm,'owned',payload(),400,validate)
    assert len(llm.client.calls)==2


def test_truncation_is_never_accepted_or_repaired_as_a_shorter_paragraph():
    class Client:
        calls=0
        def generate_structured(self,*args,**kwargs):
            self.calls+=1
            raise LLMStructuredOutputError('Truncated',response=SimpleNamespace(
                text='{"message":"Partial paragraph."}',usage=SimpleNamespace(finish_reason='length')))
    client=Client()
    with pytest.raises(LLMStructuredOutputError):
        compact_publication_copy(client,'owned',payload(),400,lambda _: {})
    assert client.calls==1


def test_unapproved_draft_can_replace_invalid_quote_only_after_source_validation():
    source=payload()
    replacement=dict(page=3,text='The exact corrected source quotation.')
    llm=gateway([dict(message='A supported paragraph.',context_evidence=[replacement],
                      companion_ids=['bound-row'])])
    checked=[]
    page=compact_publication_copy(llm,'owned',source,400,
        lambda pages: checked.append(pages['owned'].context_evidence) or {},
        preserve_inputs=False)['owned']
    assert page.context_evidence[0].page==3
    assert checked and len(llm.usage)==1
    llm=gateway([dict(message='A supported paragraph.',context_evidence=[replacement])]*2)
    with pytest.raises(AuthoredPageErrors,match='Retain every original'):
        compact_publication_copy(llm,'owned',source,400,lambda _: {})


def test_initial_repair_must_explicitly_select_rows_for_new_period_claims():
    source=payload()
    own=source['pages_to_correct']['owned']
    own['primary_observations']=[dict(metric_original='Revenue',period='FY2023')]
    own['source_rows']=[dict(id='interim-row',metric='Revenue',period='6M2024',value='42')]
    response=dict(message='Revenue is reported for 6M2024.',companion_ids=['bound-row'])
    llm=gateway([response,{**response,'companion_ids':['bound-row','interim-row']}])
    def validate(pages):
        return {} if 'interim-row' in pages['owned'].companion_ids else {'owned':['Unbound period 6M2024.']}
    page=compact_publication_copy(llm,'owned',source,400,validate,preserve_inputs=False)['owned']
    assert 'interim-row' in page.companion_ids
    assert 'eligible same-metric' in str(llm.client.calls[1]) and len(llm.usage)==2


def test_summary_references_cannot_overwrite_analysis_continuation_capacity(monkeypatch):
    from adaptive_document_agent.agent import compact_publication_copy as module
    from adaptive_document_agent.agent.retained_page_revision import revise_retained_pages
    from adaptive_document_agent.agent.retained_page_sources import writer_context,source_row_assurance
    from tests.test_live_publication_repair import ready
    from adaptive_document_agent.agent.retained_analysis import selected_record,selection_context
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage
    result,iid=ready()
    analysis=next(s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    result.presentation_plan.slides.append(analysis.model_copy(update=dict(
        id='summary',slide_type='executive_summary')))
    result.presentation_export_trace=[dict(planned_slide_id=analysis.id,slide_numbers=[5,6]),
        dict(planned_slide_id='summary',slide_numbers=[2])]
    packet,aliases=writer_context(selection_context(result,source_authoring=True))
    packet['source_row_assurance']=source_row_assurance(result,aliases)
    draft=selected_record(result)['selection']
    captured=[]
    def compact(gateway,owned,payload,limit,validate,**kwargs):
        captured.append(limit)
        return {owned:RetainedPage.model_validate(payload['pages_to_correct'][owned]['draft'])}
    monkeypatch.setattr(module,'compact_publication_copy',compact)
    revise_retained_pages(SimpleNamespace(discovery_workers=8),result,packet,aliases,draft,
        {iid:['Preserve source context.']},preserve_numeric_inputs=True)
    assert captured==[2000]


def test_structured_source_context_preserves_its_proof_and_visible_qualitative_meaning():
    source=payload()
    source['pages_to_correct']['owned']['primary_observations']=[dict(period='FY2023'),dict(period='FY2025')]
    quote='The decrease in deposits partially offset the increase in net assets.'
    llm=gateway([dict(message='The source reports revenue.',source_context=[dict(
        scope='FY2023 to FY2025',description='describes deposits as partly offsetting net asset changes',
        quote=dict(page=2,text=quote))])])
    page=compact_publication_copy(llm,'owned',source,600,lambda _: {})['owned']
    from adaptive_document_agent.agent.retained_page_sources import authored_message
    assert 'deposits as partly offsetting' in authored_message(page,['FY2023','FY2025'])
    assert any(q.page==2 and q.text==quote for q in page.all_context_evidence)
    assert page.companion_ids==['bound-row']


def test_quantitative_proof_can_support_qualitative_copy_without_publishing_its_numbers():
    source=payload();checked=[]
    proof='The share of aged inventory increased from 7% to 20% during the reporting period.'
    llm=gateway([dict(message='The source reports inventory.',source_context=[dict(
        scope='the reporting period',description='describes a shift toward aged inventory',
        quote=dict(page=2,text=proof))])])
    page=compact_publication_copy(llm,'owned',source,600,
        lambda pages: checked.append(pages['owned'].message) or {})['owned']
    from adaptive_document_agent.agent.retained_page_sources import authored_message
    assert 'describes a shift toward aged inventory.' in authored_message(page,[])
    assert '7%' not in page.message and '20%' not in page.message
    assert page.all_context_evidence[-1].text==proof and checked==[page.message]


def test_source_context_cannot_override_caller_rejection_of_the_main_direction():
    from adaptive_document_agent.agent.reported_source_context import reported_source_components
    response=dict(message='Revenue declined from FY2023 to FY2025.',source_context=[dict(
        scope='FY2023 to FY2025',description='describes a supported source qualification',
        quote=dict(page=2,text='The source explicitly reports that revenue increased.'))])
    llm=gateway([response,response])
    def validate(pages):
        page=pages['owned']
        main,parts=reported_source_components(page.message,page.context_evidence,periods=['FY2023','FY2025'])
        assert not parts and 'revenue declined' in main.casefold()
        return {'owned':['The main direction contradicts its bound revenue series.']}
    with pytest.raises(AuthoredPageErrors,match='contradicts'):
        compact_publication_copy(llm,'owned',payload(),600,validate)


@pytest.mark.parametrize('quote',['The reported amount increased by 12%.',
                                'The reported amount increased by RMB 12 million.'])
def test_structured_context_never_converts_a_quantity_into_source_only_speech(quote):
    response=dict(message='The source reports revenue.',source_context=[dict(
        scope='the named source period',description=quote,quote=dict(page=2,text=quote))])
    llm=gateway([response,response])
    with pytest.raises((AuthoredPageErrors,LLMStructuredOutputError)):
        compact_publication_copy(llm,'owned',payload(),600,lambda _: {})


def contexts(count):
    return [dict(scope='the '+name+' discussion',description='describes a material source qualification',
        quote=dict(page=2,text='Literal source quotation.'))
        for name in ['alpha','beta','gamma','delta','epsilon','zeta','eta','theta','iota'][:count]]


def test_five_distinct_source_scopes_are_not_dropped_to_fit_an_internal_array_limit():
    llm=gateway([dict(message='The source reports revenue.',source_context=contexts(5))])
    page=compact_publication_copy(llm,'owned',payload(),1200,lambda _: {})['owned']
    assert len(page.source_context)==5 and len(llm.usage)==1


@pytest.mark.parametrize('corrects',[True,False])
def test_complete_overcapacity_json_gets_one_contract_repair_without_parsing_it_as_valid(corrects):
    response=dict(message='The source reports revenue.',source_context=contexts(9))
    llm=gateway([response,{**response,'source_context':contexts(5)} if corrects else response])
    if corrects:
        assert len(compact_publication_copy(llm,'owned',payload(),1200,lambda _: {})['owned'].source_context)==5
    else:
        with pytest.raises(LLMStructuredOutputError):
            compact_publication_copy(llm,'owned',payload(),1200,lambda _: {})
    assert len(llm.client.calls)==2
