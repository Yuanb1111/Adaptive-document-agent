"""Whole-copy replacement enforces capacity without truncating source evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.compact_publication_copy import compact_publication_copy
from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors, RetainedPage
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


def test_local_copy_failure_retains_typed_candidates_and_exact_reasons_as_feedback_only():
    source=payload()
    proof='The method accounts for differences in the reporting window.'
    source['source_pages'].append(dict(page=3,text=proof))
    original=deepcopy(source)
    addition=dict(scope='measurement basis',description='Describes the reporting window.',
                  quote=dict(page=3,text=proof))
    first=dict(message='First unapproved wording.',source_context=None,source_context_additions=[addition])
    second=dict(message='Second unapproved wording.',source_context=None)
    llm=base_gateway([first,second])
    def reject(pages):
        return {'owned':['Rejected wording: '+pages['owned'].message]}

    with pytest.raises(AuthoredPageErrors) as failed:
        compact_publication_copy(llm,'owned',source,1250,reject)

    attempts=failed.value.rejected_attempts['owned']
    assert len(attempts)==len(llm.usage)==2
    assert attempts[0].page.source_context[0].model_dump()==addition
    assert attempts[0].errors==['Rejected wording: First unapproved wording.']
    assert attempts[1].page.source_context==[]
    assert attempts[1].errors==['Rejected wording: Second unapproved wording.']
    assert source==original


def test_unbound_amount_feedback_points_to_the_exact_eligible_signed_row():
    source=payload()
    row=dict(id='loss-row',metric='Operating loss',period='6M2023',value='(22,108)',unit='RMB in thousands')
    source['pages_to_correct']['owned']['source_rows']=[row,{**row,'id':'unrelated-row'}]
    draft=dict(message='The source reports operating loss.',source_context=None)
    llm=gateway([draft,{**draft,'companion_ids':['bound-row','loss-row']}])
    checks=[]

    def validate(pages):
        checks.append(pages['owned'])
        return {'owned':['No source row bound to numeric value: 22108']} if len(checks)==1 else {}

    page=compact_publication_copy(llm,'owned',source,750,validate,
        eligible_companions={'loss-row':dict(metric_original='Operating loss',period='6M2023')})['owned']

    assert page.companion_ids==['bound-row','loss-row']
    hint=llm.client.calls[1][-2]['content'].split('Exact eligible source rows matching unbound displayed amounts: ')[-1]
    assert 'loss-row' in hint and '(22,108)' in hint and 'RMB in thousands' in hint
    assert 'unrelated-row' not in hint


@pytest.mark.parametrize('nested',[False,True])
def test_selected_passage_references_restore_original_proof_before_page_validation(nested):
    from adaptive_document_agent.agent.retained_literal_proof_references import literal_proof_catalog

    source=payload()
    original='Literal wording on first line.\nChanges in working capital contributed to operating cash flow.'
    continuation='The filing also gives the related operating disclosure.'
    source['source_pages']=[dict(page=9,text=original+'\n\n'+continuation)]
    index,_=literal_proof_catalog(source['source_pages'])
    proof_id,continuation_id=index
    proof=dict(passage_id=proof_id)
    if nested:
        proof['continuation_quotes']=[dict(passage_id=continuation_id)]
    revised=dict(message='Reported levels.',source_context=[dict(scope='the source discussion',
        description='describes the contribution of working capital',quote=proof)])
    llm=gateway([revised])
    checked=[]
    page=compact_publication_copy(llm,'owned',source,400,
        lambda pages: checked.append(pages['owned'].source_context[0].quote) or {})['owned']
    assert checked==[page.source_context[0].quote]
    assert checked[0].page==9 and checked[0].text==original
    assert [q.text for q in page.source_context[0].continuation_quotes]==([continuation] if nested else [])
    assert proof_id in str(llm.client.calls[0]) and 'literal_proof_locations' in str(llm.client.calls[0])


def test_only_a_complete_overlong_description_can_remain_an_owned_repair_issue():
    import json
    from pydantic import ValidationError

    bad=dict(message='The source reports balances.',source_context=[dict(
        scope='the reported discussion',description='Describes '+('an operating constraint '*34),
        quote=dict(page=2,text='A nonliteral draft quotation.'))])

    class Client:
        calls=0
        def generate_structured(self,messages,schema,**kwargs):
            self.calls+=1
            try:
                return schema.model_validate(bad)
            except ValidationError as exc:
                raise LLMStructuredOutputError('Bounded copy response rejected',response=SimpleNamespace(
                    text=json.dumps(bad),usage=SimpleNamespace(finish_reason='stop'))) from exc

    client=Client()
    with pytest.raises(AuthoredPageErrors,match='Source context entry 1 exceeds'):
        compact_publication_copy(client,'owned',payload(),1200,lambda _: pytest.fail('No valid copy to check'))
    assert client.calls==2


def test_complete_bound_overlong_description_draft_uses_existing_description_repair(monkeypatch):
    source=payload()
    quote=dict(page=2,text=source['source_pages'][0]['text'])
    original=dict(scope='the reported discussion',description='Describes '+('a related source fact '*40),quote=quote)
    candidate=dict(message='Reported levels.',source_context=[original])
    compact='describes the source facts and related qualifications'
    llm=base_gateway([candidate,dict(context_1=compact)])
    base=llm.client.generate_text

    def complete(*args,**kwargs):
        response=base(*args,**kwargs)
        response.usage.finish_reason='stop'
        return response

    monkeypatch.setattr(llm.client,'generate_text',complete)
    checked=[]
    page=compact_publication_copy(llm,'owned',source,400,
        lambda pages: checked.append(pages['owned']) or {})['owned']
    assert checked==[page] and page.message==candidate['message']
    assert page.source_context[0].model_dump()=={**original,'description':compact}
    assert [call['operation'] for call in llm.usage]==['RetainedPageRevisions','RetainedSourceDescriptionCapacity']
    assert original['description'] in str(llm.client.calls[1])


def test_complete_source_sentences_survive_oversized_description_transport():
    sentences = [
        'Describes ' + 'the stated operational qualification and its conditions ' * 7 + 'as material.',
        'Attributes ' + 'the described change and its reported consequences ' * 7 + 'to policy.',
    ]
    proof = ' '.join(sentences)
    assert len(proof)>700
    source = payload()
    source['source_pages'][0]['text'] += ' ' + proof
    llm = gateway([dict(message='The source reports levels.', source_context=[dict(
        scope='the reported discussion', description=proof, quote=dict(page=2,text=proof))])])
    checked = []
    page = compact_publication_copy(llm,'owned',source,1000,
        lambda pages: checked.append(pages) or {})['owned']
    assert [item.description for item in page.source_context]==sentences
    assert all(item.quote.text==proof and item.quote.page==2 for item in page.source_context)
    assert len(checked)==1 and len(llm.usage)==1


def test_only_exact_bound_calendar_spellings_normalize_before_capacity_validation():
    source=payload()
    source['pages_to_correct']['owned']['primary_observations']=[dict(period='2024-06-30')]
    llm=gateway([dict(message='As of June 30, 2024.')])
    # Canonical spelling fits; its literal calendar identity is unchanged.
    assert compact_publication_copy(llm,'owned',source,18,lambda _: {})['owned'].message=='As of 2024-06-30.'
    llm=gateway([dict(message='As of June 29, 2024.')]*2)
    with pytest.raises(LLMStructuredOutputError):
        compact_publication_copy(llm,'owned',source,18,lambda _: {})


@pytest.mark.parametrize('tight_budget', [False, True])
def test_qualified_shared_direction_subject_is_repeated_before_validation(tight_budget):
    source = payload()
    own = source['pages_to_correct']['owned']
    own['primary_observations'] = [dict(id=f'cash-{year}', metric_original='Operating balance',
        period=f'FY{year}', period_type='fiscal_year', value=value, table_id='table-A', row_id=2)
        for year, value in [(2021, 10), (2022, 20), (2023, 15)]]
    original = 'Operating balance rose from FY2021 to FY2022, and fell from FY2022 to FY2023.'
    expanded = ('Operating balance rose from FY2021 to FY2022. '
                'Operating balance fell from FY2022 to FY2023.')
    compact = 'Operating balance levels were 10 in FY2021, 20 in FY2022, and 15 in FY2023.'
    llm = gateway([dict(message=original), dict(message=compact)] if tight_budget else [dict(message=original)])
    checked = []

    output = compact_publication_copy(llm, 'owned', source, len(original) if tight_budget else 400,
        lambda pages: checked.append(pages['owned'].message) or {})['owned']

    assert checked == ([expanded, compact] if tight_budget else [expanded])
    assert output.message == (compact if tight_budget else expanded)
    assert output.companion_ids == own['draft']['companion_ids']
    assert output.context_evidence[0].text == own['draft']['context_evidence'][0]['text']
    assert len(llm.usage) == (2 if tight_budget else 1)


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


@pytest.mark.parametrize('corrects',[True,False])
def test_shared_budget_identifies_overlong_explanations_without_shortening_their_proof(corrects):
    from adaptive_document_agent.agent.compact_publication_copy import visible_copy_budget
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage
    source=payload();proof=source['source_pages'][0]['text']
    context=dict(scope='the reported discussion',description='describes '+('the source qualification; '*20),
                 quote=dict(page=2,text=proof))
    rejected=dict(message='The source reports levels.',source_context=[context])
    compact='describes the source qualification' if corrects else context['description']
    llm=base_gateway([rejected,dict(context_1=compact)])
    if corrects:
        page=compact_publication_copy(llm,'owned',source,400,lambda _: {})['owned']
        assert page.source_context[0].quote.text==proof
        assert page.source_context[0].scope==context['scope'] and page.message==rejected['message']
        assert page.companion_ids==['bound-row']
        assert visible_copy_budget(page,[],400)['total_characters']<=400
    else:
        with pytest.raises(AuthoredPageErrors,match='Measured shared visible-copy budget'):
            compact_publication_copy(llm,'owned',source,400,lambda _: {})
    assert len(llm.client.calls)==2
    assert llm.usage[-1]['operation']=='RetainedSourceDescriptionCapacity'
    feedback=str(llm.client.calls[1])
    assert 'source_context_characters' in feedback and 'required_reduction_characters' in feedback
    assert 'message_budget_with_current_context' in feedback
    assert 'drafting_target_message_characters' in feedback and 'drafting_target_characters' in feedback
    assert source==payload()


def test_capacity_prompt_has_per_field_drafting_bounds_and_preserves_shared_validation():
    from adaptive_document_agent.agent.compact_publication_copy import (
        _source_description_capacity_request,visible_copy_budget)
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage

    page=RetainedPage(title='Source',message='Reported levels.',companion_ids=[],source_context=[dict(
        scope=scope,description='describes '+('the source qualification; '*10),
        quote=dict(page=index+1,text='Complete literal source proof.'))
        for index,scope in enumerate(('the initial discussion','the later discussion'))])
    schema,messages=_source_description_capacity_request(page,visible_copy_budget(page,[],400),400,[])
    fields=schema.model_json_schema()['properties']
    assert len(fields)==2 and all(field['items']['maxLength']==700 for field in fields.values())
    assert 'Target ' in fields['context_1']['description']
    assert 'ordered list of short paragraphs' in messages[0]['content']
    assert schema.model_validate({'context_1':'a'*300,'context_2':['A short explanation.']})


@pytest.mark.parametrize('response_style',['paragraphs','overlong_paragraph','legacy_string'])
def test_capacity_repair_preserves_each_complete_paragraph_and_its_literal_proof(monkeypatch,response_style):
    source=payload()
    quote=dict(page=2,text=source['source_pages'][0]['text'])
    scope='the reported discussion'
    candidate=dict(message='Reported levels.',source_context=[dict(scope=scope,
        description='Describes '+('a related source fact '*40),quote=quote)])
    paragraphs=[f'Describes the source qualification {word}.' + ' Related obligations increased.'*13
                for word in ('before the transition','after the transition')]
    combined=' '.join(paragraphs)
    assert len(combined)>700 and all(len(paragraph)<700 for paragraph in paragraphs)
    response={'paragraphs':paragraphs,'overlong_paragraph':[combined],'legacy_string':combined}[response_style]
    llm=base_gateway([candidate,dict(context_1=response)])
    base=llm.client.generate_text

    def complete(*args,**kwargs):
        response=base(*args,**kwargs)
        response.usage.finish_reason='stop'
        return response

    monkeypatch.setattr(llm.client,'generate_text',complete)
    checked=[]
    page=compact_publication_copy(llm,'owned',source,1250,
        lambda pages: checked.append(pages['owned']) or {})['owned']
    assert checked==[page] and page.message==candidate['message']
    assert all(item.scope==scope and item.quote.model_dump()==quote for item in page.source_context)
    assert ' '.join(item.description.removeprefix('Reports the following. ') for item in page.source_context)==combined
    assert [call['operation'] for call in llm.usage]==['RetainedPageRevisions','RetainedSourceDescriptionCapacity']


def test_dense_capacity_uses_complete_condensed_option_when_full_version_overflows():
    from adaptive_document_agent.agent.compact_publication_copy import (
        _source_capacity_values, _source_description_capacity_request, visible_copy_budget)
    page=RetainedPage(title='Source profile',message='Reported levels.',source_context=[dict(
        scope=f'the {scope} discussion',description='Describes the reported operating condition. '*6,
        quote=dict(page=index,text='Full literal proof for the given condition.'))
        for index,scope in enumerate(('initial','local','market','balance','closing'),1)])
    limit=900
    schema,_=_source_description_capacity_request(page,visible_copy_budget(page,[],limit),limit,[])
    condensed={f'context_{index}':['Describes the reported operating condition.']
        for index in range(1,6)}
    condensed['context_1']=['Describes 30 facilities.']
    response=schema.model_validate({**{f'context_{index}':[item.description]
        for index,item in enumerate(page.source_context,1)},'condensed':condensed})
    actual=RetainedPage.model_validate(_source_capacity_values(page,response,[],limit))
    assert visible_copy_budget(page,[],limit)['total_characters']>limit
    assert visible_copy_budget(actual,[],limit)['total_characters']<=limit
    assert actual.message==page.message and actual.all_context_evidence==page.all_context_evidence
    assert actual.source_context[0].description==page.source_context[0].description
    assert [item.scope for item in actual.source_context]==[item.scope for item in page.source_context]


def test_capacity_wire_keeps_usable_alternative_to_an_overlong_source_paragraph():
    from adaptive_document_agent.agent.compact_publication_copy import (
        _source_capacity_values, _source_description_capacity_request, visible_copy_budget)

    page=RetainedPage(title='Source profile',message='Reported levels.',source_context=[dict(
        scope=f'the {scope} discussion',description='Describes the reported operating condition.',
        quote=dict(page=index,text='Full literal proof for the given condition.'))
        for index,scope in enumerate(('initial','local','market','balance','closing'),1)])
    limit=1600
    schema,_=_source_description_capacity_request(page,visible_copy_budget(page,[],limit),limit,[])
    short={f'context_{index}':[item.description] for index,item in enumerate(page.source_context,1)}
    overlong='Describes operating conditions as '+('reported in the accompanying original evidence ' * 16)+'.'
    response=schema.model_validate({**short,'context_3':[overlong],'condensed':short})

    actual=RetainedPage.model_validate(_source_capacity_values(page,response,[],limit))

    assert actual==page


@pytest.mark.parametrize('usable_version',['primary','condensed','neither'])
def test_full_page_chooses_only_a_source_version_that_fits_its_last_slot(usable_version):
    from pydantic import ValidationError
    from adaptive_document_agent.agent.compact_publication_copy import (
        _source_capacity_values, _source_description_capacity_request, visible_copy_budget)

    scopes=('assembly','delivery','sales','orders','staff','returns','products','support')
    page=RetainedPage(title='Source profile',message='Reported levels.',source_context=[
        dict(scope=scope,description='Describes the local operating condition.',
             quote=dict(page=index,text=f'The reported condition concerns {scope}.'))
        for index,scope in enumerate(scopes,1)])
    limit=1600
    schema,messages=_source_description_capacity_request(page,visible_copy_budget(page,[],limit),limit,[])
    compact={f'context_{index}':[item.description] for index,item in enumerate(page.source_context,1)}
    split={**compact,'context_3':['Describes the local operating condition.',
                                  'Reports that operating procedures changed.']}
    response=schema.model_validate({
        **(compact if usable_version=='primary' else split),
        'condensed':compact if usable_version=='condensed' else split})
    assert 'exactly ONE paragraph for each scope' in messages[0]['content']

    values=_source_capacity_values(page,response,[],limit)
    if usable_version=='neither':
        with pytest.raises(ValidationError,match='at most 8'):
            RetainedPage.model_validate(values)
    else:
        assert RetainedPage.model_validate(values)==page


def test_size_only_compression_keeps_exact_source_day_count_parameters():
    from adaptive_document_agent.agent.compact_publication_copy import (
        _source_capacity_values, _source_description_capacity_request, visible_copy_budget)

    methodology='Describes the calculation as using 360 days for a given year and 180 days for a six-month period.'
    page=RetainedPage(title='Turnover',message='Reported levels.',source_context=[
        dict(scope='turnover days calculation',description=methodology,quote=dict(page=2,text=
            'The calculation multiplies by the number of days (360 days for a given year and '
            '180 days for a six-month period).')),
        dict(scope='trade receivable movements',description='Describes changes in receivables. '*12,
            quote=dict(page=3,text='The receivable balance changed with customer collections.')),
    ])
    limit=430
    schema,_=_source_description_capacity_request(page,visible_copy_budget(page,[],limit),limit,[])
    assert set(schema.model_fields)=={'context_2'}
    response=schema.model_validate({'context_2':['Describes changes with customer collections.']})
    actual=RetainedPage.model_validate(_source_capacity_values(page,response,[],limit))
    assert actual.source_context[0]==page.source_context[0]
    assert actual.all_context_evidence==page.all_context_evidence
    assert visible_copy_budget(page,[],limit)['total_characters']>limit
    assert visible_copy_budget(actual,[],limit)['total_characters']<=limit


@pytest.mark.parametrize('scope,repair_description_only',[('the reported discussion',True),('FY2099',False)])
def test_overbudget_unbound_numeric_description_uses_frozen_scope_only_when_supported(scope,repair_description_only):
    source=payload()
    quote=dict(page=2,text=source['source_pages'][0]['text'])
    candidate=dict(message='Reported levels.',source_context=[dict(scope=scope,
        description='reports 40% margins; '+('describes some source context. '*12),quote=quote)])
    eligible={'context_1':'describes the historical margin context'}
    replacement={**candidate,'source_context':[dict(scope='the reported discussion',
        description=eligible['context_1'],quote=quote)]}
    llm=base_gateway([candidate,eligible if repair_description_only else replacement])
    page=compact_publication_copy(llm,'owned',source,400,lambda _: {})['owned']
    assert page.source_context[0].description==eligible['context_1']
    assert page.source_context[0].quote.text==quote['text']
    assert len(llm.client.calls)==2
    assert llm.usage[-1]['operation']==('RetainedSourceDescriptionCapacity' if repair_description_only
                                       else 'RetainedPageRevisions')
    if repair_description_only:
        assert '"description_requires_qualitative_rewrite": true' in str(llm.client.calls[1])


def test_adjacent_identical_source_scopes_share_display_prefix_without_merging_proof():
    from adaptive_document_agent.agent.compact_publication_copy import visible_copy_budget
    from adaptive_document_agent.agent.reported_source_context import reported_source_components
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage,authored_message,authored_visible_copy

    scopes=['the earliest discussion',*['the described reporting comparison']*4,'the later discussion']
    qualifiers=['demand','capacity','expense','procurement','receivables','deployment']
    page=RetainedPage(title='Source',message='Reported levels.',source_context=[dict(scope=scope,
        description=f'describes the related {qualifier} qualification',
        quote=dict(page=index+1,text=f'Literal source for the {qualifier} qualification.'))
        for index,(scope,qualifier) in enumerate(zip(scopes,qualifiers,strict=True))])
    before=page.model_copy(deep=True)
    complete=authored_message(page,[])
    _,bound=reported_source_components(complete,page.all_context_evidence,declared=page.source_context)
    visible=authored_visible_copy(page,[])
    assert len(bound)==6 and visible.count('For the described reporting comparison, ')==2
    assert visible.count('The source also describes')==2 and len(visible)<len(complete)
    assert all(qualifier in visible for qualifier in qualifiers)
    assert visible_copy_budget(page,[],2000)['total_characters']==len(visible)
    assert page==before


def test_long_literal_proof_is_complete_and_excluded_from_visible_copy_budget():
    from adaptive_document_agent.agent.compact_publication_copy import visible_copy_budget
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage
    proof='Complete literal source proof. '*40
    page=RetainedPage(title='Source',message='Reported levels.',companion_ids=[],source_context=[dict(
        scope='the source discussion',description='describes the reported qualification',quote=dict(page=2,text=proof))])
    before=page.model_copy(deep=True)
    measured=visible_copy_budget(page,[],200)
    assert measured['total_characters']<200<len(proof)
    assert not measured['proof_quotations_count_toward_budget'] and not measured['semantic_approval']
    assert page==before


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
    response=dict(message='Revenue is reported for 6M2024.',companion_ids=['bound-row'],
                  context_evidence=source['pages_to_correct']['owned']['draft']['context_evidence'])
    llm=gateway([response,{**response,'companion_ids':['bound-row','interim-row']}])
    def validate(pages):
        return {} if 'interim-row' in pages['owned'].companion_ids else {'owned':['Unbound period 6M2024.']}
    page=compact_publication_copy(llm,'owned',source,400,validate,preserve_inputs=False)['owned']
    assert 'interim-row' in page.companion_ids
    assert 'eligible same-metric' in str(llm.client.calls[1]) and len(llm.usage)==2


def test_initial_repair_cannot_silently_keep_a_rejected_draft_quote_via_null():
    response=dict(message='The source reports levels.',companion_ids=[],context_evidence=None)
    llm=gateway([response,{**response,'context_evidence':[]}])
    page=compact_publication_copy(llm,'owned',payload(),400,lambda _: {},preserve_inputs=False)['owned']
    assert page.context_evidence==[] and len(llm.client.calls)==2


def test_source_only_revision_can_retain_exact_main_numeric_text():
    source=payload()
    original=source['pages_to_correct']['owned']['draft']['message']
    proof=source['source_pages'][0]['text']
    llm=gateway([dict(message=None,source_context=[dict(scope='the reported discussion',
        description='Describes the source qualification.',quote=dict(page=2,text=proof))])])
    page=compact_publication_copy(llm,'owned',source,1250,lambda _: {})['owned']
    assert page.message==original
    assert page.source_context[0].quote.text==proof
    assert len(llm.client.calls)==1


def test_addressed_source_description_edit_keeps_other_copy_and_exact_proof():
    source=payload()
    draft=source['pages_to_correct']['owned']['draft']
    proof=dict(page=2,text=source['source_pages'][0]['text'])
    draft['source_context']=[dict(scope=f'the {name} discussion',
        description=f'Describes the {name} source explanation.',quote=proof) for name in ('first','second')]
    replacement='Describes the source qualification and its stated cause.'
    llm=gateway([dict(message=None,source_context=None,source_context_edits={'context-1':replacement})])
    page=compact_publication_copy(llm,'owned',source,1250,lambda _: {})['owned']
    assert page.message==draft['message']
    assert page.source_context[0].model_dump()==draft['source_context'][0]
    assert page.source_context[1].model_dump()=={**draft['source_context'][1],'description':replacement}
    assert len(llm.client.calls)==1


@pytest.mark.parametrize('rewrite_description',[False,True])
def test_existing_source_scope_can_be_corrected_without_adding_another_entry(rewrite_description):
    source=payload()
    draft=source['pages_to_correct']['owned']['draft']
    proof=dict(page=2,text='From December 31, 2021 to June 30, 2024, the product mix changed.')
    source['source_pages'][0]['text']=proof['text']
    original=dict(scope='the reported discussion',description='Describes a change in product mix.',quote=proof)
    sibling=dict(scope='the product categories',description='Describes the reported categories.',quote=proof)
    draft['source_context']=[original,sibling]
    edit=dict(scope='December 31, 2021 to June 30, 2024')
    if rewrite_description:
        edit['description']='Describes the change in the mix of reported products.'
    llm=gateway([dict(message=None,source_context=None,source_context_edits={'context-0':edit})])
    reviewed=[]

    page=compact_publication_copy(llm,'owned',source,1250,
        lambda pages: reviewed.append(pages['owned']) or {})['owned']

    assert reviewed==[page] and len(llm.client.calls)==1
    assert [item.model_dump() for item in page.source_context]==[{**original,**edit},sibling]


def test_revised_scope_still_requires_a_bound_period():
    source=payload()
    proof=dict(page=2,text=source['source_pages'][0]['text'])
    source['pages_to_correct']['owned']['draft']['source_context']=[dict(
        scope='reported discussion',description='Describes the source qualification.',quote=proof)]
    invalid=dict(message=None,source_context=None,source_context_edits={'context-0':{'scope':'FY2099'}})
    llm=gateway([invalid,invalid])

    with pytest.raises(AuthoredPageErrors,match='Scope binding feedback'):
        compact_publication_copy(llm,'owned',source,1250,lambda _: {})


def test_addressed_source_addition_retains_existing_scope_and_proof():
    source=payload()
    draft=source['pages_to_correct']['owned']['draft']
    proof=dict(page=2,text=source['source_pages'][0]['text'])
    draft['source_context']=[dict(scope='main discussion',description='Describes the main finding.',quote=proof)]
    addition=dict(scope='measurement basis',description='Describes the source measurement approach.',quote=proof)
    llm=gateway([dict(message=None,source_context=None,source_context_additions=[addition])])

    page=compact_publication_copy(llm,'owned',source,1250,lambda _: {})['owned']

    assert page.message==draft['message']
    assert [item.model_dump() for item in page.source_context]==[*draft['source_context'],addition]
    assert len(llm.client.calls)==1


@pytest.mark.parametrize('preserve', [False, True])
def test_full_addressed_proof_edit_uses_the_same_literal_catalog_and_keeps_other_slots(preserve):
    from adaptive_document_agent.agent.retained_literal_proof_references import literal_proof_catalog
    source=payload()
    original=dict(page=2,text='The service is monitored.')
    earlier=dict(page=2,text='The original review covered initial service conditions.')
    later=dict(page=3,text='A subsequent review covered service delivery conditions.')
    source['source_pages']=[dict(page=2,text=original['text']+'\n\n'+earlier['text']),later]
    catalog,_=literal_proof_catalog(source['source_pages'])
    first_ref,early_ref,later_ref=catalog
    first=dict(scope='the review',description='Describes the service review.',quote=original,
               continuation_quotes=[earlier])
    sibling=dict(scope='the service',description='Describes service monitoring.',quote=original)
    draft=source['pages_to_correct']['owned']['draft']
    draft['context_evidence']=[]
    draft['source_context']=[first,sibling]
    edit=dict(scope='the review',description='Describes the review of service delivery.',
              quote=dict(passage_id=first_ref if preserve else later_ref))
    if preserve:
        edit['continuation_quotes']=[dict(passage_id=early_ref),dict(passage_id=later_ref)]
    response=dict(message=None,source_context=None,source_context_edits={'context-0':edit},
                  companion_ids=draft['companion_ids'],context_evidence=draft['context_evidence'])
    checked=[]
    page=compact_publication_copy(base_gateway([response]),'owned',source,1500,
        lambda pages: checked.append(pages['owned']) or {},preserve_inputs=preserve)['owned']
    assert checked==[page] and page.source_context[1].model_dump()==sibling
    assert [q.model_dump() for q in page.source_context[0].proof_quotes]==(
        [original,earlier,later] if preserve else [later])


@pytest.mark.parametrize('defect', ['unknown_ref','wrong_page','extra_ref_field','wrong_slot',
                                    'frozen_proof_removed','missing_description','orphan_continuation'])
def test_full_addressed_proof_edit_rejects_unbound_or_incomplete_proofs(defect):
    from adaptive_document_agent.agent.retained_literal_proof_references import literal_proof_catalog
    source=payload()
    source['source_pages'].append(dict(page=3,text='Additional evidence from the adjoining page.'))
    catalog,_=literal_proof_catalog(source['source_pages'])
    old_ref,new_ref=catalog
    old=catalog[old_ref].model_dump()
    original=dict(scope='the review',description='Describes the service review.',quote=old)
    source['pages_to_correct']['owned']['draft']['source_context']=[original,{**original,'scope':'the service'}]
    edit=dict(scope='the review',description='Describes the service assessment.',quote=dict(passage_id=old_ref),
              continuation_quotes=[dict(passage_id=new_ref)])
    slot='context-0'
    if defect=='unknown_ref':
        edit['continuation_quotes']=[dict(passage_id='missing')]
    elif defect=='wrong_page':
        edit['quote']={**old,'page':3}
    elif defect=='extra_ref_field':
        edit['quote']['page']=2
    elif defect=='wrong_slot':
        slot='context-2'
    elif defect=='frozen_proof_removed':
        # Even though the sibling keeps the old passage, this frozen slot cannot discard it.
        edit.update(quote=dict(passage_id=new_ref),continuation_quotes=[])
    elif defect=='missing_description':
        edit.pop('description')
    else:
        edit.pop('quote')
    response=dict(message=None,source_context=None,source_context_edits={slot:edit})
    with pytest.raises(LLMStructuredOutputError):
        compact_publication_copy(base_gateway([response,response]),'owned',source,1500,
                                 lambda _: pytest.fail('Invalid proof reached page validation'))


@pytest.mark.parametrize('outcome', ['qualitative', 'unbound_rate', 'over_wire_limit'])
def test_long_full_edit_reflows_with_its_proof_and_keeps_the_scoped_content_checks(outcome):
    from adaptive_document_agent.agent.retained_literal_proof_references import literal_proof_catalog

    source=payload()
    quote=source['source_pages'][0]
    continuation=dict(page=3,text='Management monitored conditions and reported a share of 40%.')
    source['source_pages'].append(continuation)
    first_ref,second_ref=literal_proof_catalog(source['source_pages'])[0]
    original=dict(scope='the service discussion',description='Describes service conditions.',quote=quote)
    sibling={**original,'description':'Describes an independent source condition.'}
    source['pages_to_correct']['owned']['draft']['source_context']=[original,sibling]
    statements=['Describes conditions for '+('service delivery during the reported period, '*8)+'as reported.',
                'Reports the source assessment of '+('quality under the stated operating conditions, '*8)+'as disclosed.']
    if outcome=='unbound_rate':
        statements[1]+=' The share was 40%.'
    description=' '.join(statements)
    assert 700<len(description)<2100
    if outcome=='over_wire_limit':
        description+='x'*(2101-len(description))
    edit={**original,'description':description,'quote':dict(passage_id=first_ref),
          'continuation_quotes':[dict(passage_id=second_ref)]}
    reply=dict(message=None,source_context=None,source_context_edits={'context-0':edit})
    gateway=base_gateway([reply,reply])
    validated=[]
    def check(pages):
        validated.append(pages['owned'])
        return {}
    if outcome=='unbound_rate':
        with pytest.raises(AuthoredPageErrors,match='without unbound numbers'):
            compact_publication_copy(gateway,'owned',source,2000,check)
    elif outcome=='over_wire_limit':
        with pytest.raises(LLMStructuredOutputError):
            compact_publication_copy(gateway,'owned',source,2000,check)
        assert not validated
        return
    else:
        page=compact_publication_copy(gateway,'owned',source,2000,check)['owned']
        assert validated==[page]
    for page in validated:
        assert page.source_context[-1].model_dump()==sibling
        assert all(item.scope==original['scope'] and len(item.description)<=700
                   for item in page.source_context[:-1])
        assert ' '.join(item.description.removeprefix('Reports the following. ')
                        for item in page.source_context[:-1])==description
        assert all([q.model_dump() for q in item.proof_quotes]==[quote,continuation]
                   for item in page.source_context[:-1])


def test_overlong_addressed_description_preserves_complete_explanations_and_their_proof():
    source=payload()
    draft=source['pages_to_correct']['owned']['draft']
    proof=dict(page=2,text=source['source_pages'][0]['text'])
    draft['source_context']=[dict(scope='measurement basis',description='Describes the original finding.',quote=proof)]
    statements=['Describes the assessment as '+('detailed and source-supported ' * 15)+'.',
                'Reports management’s assessment as '+('qualified by original evidence ' * 14)+'.']
    llm=gateway([dict(message=None,source_context=None,source_context_edits={'context-0':' '.join(statements)})])

    page=compact_publication_copy(llm,'owned',source,1600,lambda _: {})['owned']

    assert [item.description for item in page.source_context]==statements
    assert all(item.scope=='measurement basis' and item.quote.model_dump()==proof for item in page.source_context)
    assert len(llm.client.calls)==1


def test_overlong_merged_edit_compresses_only_that_description_when_page_fits():
    source=payload()
    draft=source['pages_to_correct']['owned']['draft']
    proof=dict(page=2,text=source['source_pages'][0]['text'])
    fixed=dict(scope='reported context',description='Describes the confirmed condition.',quote=proof)
    draft['source_context']=[dict(scope='measurement basis',description='Describes the original finding.',quote=proof),fixed]
    overlong='Describes the assessment as '+('detailed and source-supported ' * 25)+'.'
    shorter='Describes the assessment as supported by the original evidence.'
    llm=base_gateway([dict(message=None,source_context=None,source_context_edits={'context-0':overlong}),
                     dict(context_1=[shorter])])

    page=compact_publication_copy(llm,'owned',source,1600,lambda _: {})['owned']

    assert page.source_context[0].description==shorter
    assert page.source_context[1].model_dump()==fixed
    assert [call['operation'] for call in llm.usage]==['RetainedPageRevisions','RetainedSourceDescriptionCapacity']


@pytest.mark.parametrize('shared_overflow',[0,23])
def test_full_source_list_repairs_only_the_overlong_slot_when_siblings_fit(monkeypatch,shared_overflow):
    from adaptive_document_agent.agent.compact_publication_copy import visible_copy_budget

    source=payload()
    proof=dict(page=2,text=source['source_pages'][0]['text'])
    scopes=('assembly','delivery','sales','orders','staff','returns','products','support')
    contexts=[dict(scope=scope,description='Describes local conditions.',quote=proof) for scope in scopes]
    overlong='Describes '+('the reported operating conditions '*22).strip()+'.'
    candidate=[*contexts[:6],{**contexts[6],'description':overlong},contexts[7]]
    page=RetainedPage.model_validate({**source['pages_to_correct']['owned']['draft'],'source_context':contexts})
    draft=page.model_copy(update={'source_context':[
        item.model_copy(update={'description':record['description']})
        for item,record in zip(page.source_context,candidate,strict=True)]})
    limit=visible_copy_budget(draft,[],3000)['total_characters']-shared_overflow
    llm=base_gateway([dict(message=None,source_context=candidate),dict(context_7='Describes local conditions.')])
    generate=llm.client.generate_text
    def complete(*args,**kwargs):
        value=generate(*args,**kwargs)
        value.usage.finish_reason='stop'
        return value
    monkeypatch.setattr(llm.client,'generate_text',complete)

    result=compact_publication_copy(llm,'owned',source,limit,lambda _: {})['owned']

    assert result.model_dump()==page.model_dump()
    assert [row['operation'] for row in llm.usage]==['RetainedPageRevisions','RetainedSourceDescriptionCapacity']
    assert 'context_7' in str(llm.client.calls[1])
    assert 'context_1' not in str(llm.client.calls[1])


@pytest.mark.parametrize('analysis_pages,expected_target', [([5],600),([5,6],None)])
def test_final_copy_draft_target_keeps_the_actual_analysis_page_cost(
        monkeypatch,analysis_pages,expected_target):
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
    result.presentation_export_trace=[dict(planned_slide_id=analysis.id,slide_numbers=analysis_pages),
        dict(planned_slide_id='summary',slide_numbers=[2])]
    packet,aliases=writer_context(selection_context(result,source_authoring=True))
    packet['source_row_assurance']=source_row_assurance(result,aliases)
    draft=selected_record(result)['selection']
    from adaptive_document_agent.agent.retained_page_sources import RejectedPageAttempt
    original=deepcopy(next(decision['page'] for decision in draft['decisions'] if decision['insight_id']==iid))
    prior=RejectedPageAttempt(page=RetainedPage(title='Rejected candidate',message='Rejected wording.'),
                              errors=['Missing exact dated comparison'])
    captured=[]
    def compact(gateway,owned,payload,limit,validate,**kwargs):
        packet=payload['pages_to_correct'][owned]
        assert packet['draft']==original
        assert packet['rejected_page_attempts']==[prior.model_dump(mode='json')]
        captured.append((limit,payload['local_message_character_targets'].get(owned)))
        return {owned:RetainedPage.model_validate(payload['pages_to_correct'][owned]['draft'])}
    monkeypatch.setattr(module,'compact_publication_copy',compact)
    revise_retained_pages(SimpleNamespace(discovery_workers=8),result,packet,aliases,draft,
        {iid:['Preserve source context.']},preserve_numeric_inputs=True,rejected_attempts={iid:[prior]})
    assert captured==[(2000,expected_target)]


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


def test_overlong_explicitly_attributed_edit_leaves_the_repair_for_invalid_sibling_copy():
    source=payload()
    proof=dict(page=2,text='Literal source quotation.')
    items=[dict(scope='the reporting period',description='Describes reported conditions.',quote=proof),
           dict(scope='the assessment period',description='Describes assessment of the service.',quote=proof)]
    source['pages_to_correct']['owned']['draft']['source_context']=items
    first='For the service during the assessment period, the source links delays to staffing. '
    conditions='Management assessed the reported conditions and considered the impact on the service. '
    closing='Management confirmed that its review considered the available evidence.'
    description=first+conditions*8+closing
    assert len(description)>700
    candidate=dict(message=None,source_context=None,source_context_edits={
        'context-0':'Reports a decline of 45%.','context-1':description})
    corrected={**candidate,'source_context_edits':{
        'context-0':'Reports a decline in service levels.','context-1':description}}
    llm=base_gateway([candidate,corrected])
    page=compact_publication_copy(llm,'owned',source,2500,lambda _: {})['owned']
    assert [call['operation'] for call in llm.usage]==['RetainedPageRevisions','RetainedPageRevisions']
    assert '45%' in str(llm.client.calls[1])
    assert page.source_context[0].description==corrected['source_context_edits']['context-0']
    parts=page.source_context[1:]
    assert len(parts)>1 and all(len(item.description)<=700 for item in parts)
    assert ' '.join(item.description.removeprefix('Reports the following. ') for item in parts)==description
    assert all(item.scope=='the assessment period' and item.quote.model_dump()==proof for item in parts)


def test_local_length_request_cannot_reassign_sibling_issues_or_license_proof_only_amounts():
    from adaptive_document_agent.agent.compact_publication_copy import (
        _source_capacity_values, _source_description_capacity_request, visible_copy_budget)
    from adaptive_document_agent.agent.reported_source_context import (
        qualified_source_statement, reported_source_components)

    proof=dict(page=3,text='During the review period, the affected share increased to 20%.')
    page=RetainedPage(title='Service',message='Reported levels.',source_context=[
        dict(scope='the reporting period',description='Reports a change in service demand.',
             quote=dict(page=2,text='The service experienced demand growth.')),
        dict(scope='the review period',description='Describes how the affected share increased.',quote=proof)])
    limit=2500
    schema,messages=_source_description_capacity_request(page,visible_copy_budget(page,[],limit),
        limit,['Correct a different item about service demand.'],editable_indexes=[1])
    assert set(schema.model_fields)=={'context_2'}
    assert 'Correct a different item about service demand.' not in messages[1]['content']
    statement='Explains the assessment process. '+(
        'The observed movement reflected a change in conditions during the review period. '*8
    )+'Management said the affected share increased to 20%.'
    assert len(statement)>700
    response=schema.model_validate({'context_2':[statement]})
    actual=RetainedPage.model_validate(_source_capacity_values(page,response,[],limit))
    assert actual.source_context[0]==page.source_context[0]
    assert len(actual.source_context)>2 and all(len(item.description)<=700 for item in actual.source_context)
    item=next(i for i in actual.source_context if '20%' in i.description)
    assert item.quote.model_dump()==proof
    text=qualified_source_statement(item)
    assert text not in reported_source_components('Reported levels. '+text,actual.all_context_evidence,
                                                  declared=[item])[1]
