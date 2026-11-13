"""Literal qualitative source speech stays visible and cannot license numbers."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.reported_source_context import reported_source_components
from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_page_sources import (
    page_bindings,validate_authored_pages,AuthoredPageErrors,bound_authored_slide_ids)
from adaptive_document_agent.models import DocumentPage
from adaptive_document_agent.models.executive_brief import BriefQuote
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway,verdict

QUOTE='The decrease in deposits partially offset the increase in net current assets.'


def reported():
    result,_,selection=fixture()
    result.document.pages.append(DocumentPage(page_number=235,text=QUOTE))
    result.document.page_count=max(result.document.page_count,235)
    page=selection.decisions[0].page
    page.message='The source reports revenue. For FY2023 to FY2025, the source states: "'+QUOTE+'"'
    page.context_evidence=[BriefQuote(page=235,text=QUOTE)]
    return result,selection


def paraphrased():
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
    result,selection=reported()
    page=selection.decisions[0].page
    page.message='The source reports revenue.'
    page.source_context=[QualifiedSourceCopy(scope='FY2023 to FY2025',
        description='attributes net current asset changes partly to lower deposits',
        quote=BriefQuote(page=235,text=QUOTE))]
    page.context_evidence=[]
    return result,selection


@pytest.mark.parametrize('identifier',['COVID-19','Model-Q24'])
def test_source_bound_identifier_survives_compilation_with_empty_numeric_scope(identifier):
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    result,selection=paraphrased()
    item=selection.decisions[0].page.source_context[0]
    item.description=f'describes demand disruption associated with {identifier}'
    item.quote.text=f'The source describes demand disruption associated with {identifier}.'
    result.document.pages[-1].text=item.quote.text
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete source selection.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    assert identifier in slide.bullets[1] and slide.bullet_observation_ids[1]==[]
    assert PresentationPlanValidator().validate(plan,result) is plan


@pytest.mark.parametrize('count',[5,8])
def test_many_qualifications_compile_losslessly_under_the_bullet_limit(count):
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy,qualified_source_statement
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    result,selection=paraphrased()
    page=selection.decisions[0].page
    names=['alpha','beta','gamma','delta','epsilon','zeta','eta','theta'][:count]
    page.source_context=[QualifiedSourceCopy(scope=f'the {name} discussion',
        description='describes a material source qualification',quote=BriefQuote(page=235,text=QUOTE))
        for name in names]
    expected=' '.join(qualified_source_statement(item) for item in page.source_context)
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete source selection.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    assert len(slide.bullets)==5 and ' '.join(slide.bullets[1:])==expected
    assert all(not ids for ids in slide.bullet_observation_ids[1:])
    assert PresentationPlanValidator().validate(plan,result) is plan
    assert not review_complete(result)
    slide.bullets[-1]+=' An unbound amount of 123 units.'
    with pytest.raises(ValueError):PresentationPlanValidator().validate(plan,result)


@pytest.mark.parametrize('identifier',['Unknown-Q24','USD120','FY2099','Q1-2024'])
def test_unknown_identifier_currency_and_period_claims_cannot_be_qualitative(identifier):
    result,selection=paraphrased()
    item=selection.decisions[0].page.source_context[0]
    item.description=f'describes demand disruption associated with {identifier}'
    item.quote.text='The source describes demand disruption associated with Model-Q24 and USD120 in FY2099 and Q1-2024.'
    result.document.pages[-1].text=item.quote.text
    with pytest.raises(AuthoredPageErrors):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)


def test_declared_qualitative_paraphrase_is_visible_and_needs_a_fresh_semantic_verdict():
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    result,selection=paraphrased()
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete source selection.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    assert slide.message=='The source reports revenue.'
    assert 'lower deposits' in slide.bullets[1] and slide.bullet_observation_ids[1]==[]
    assert 235 in slide.source_pages and not review_complete(result)


def test_declaring_source_context_cannot_approve_its_own_meaning():
    from adaptive_document_agent.agent.retained_analysis_review import review_complete,review_retained_analysis
    result,selection=paraphrased()
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic selection coverage only.')]),result)
    result.presentation_plan=retained.compile_retained_analysis(result)
    rejected=verdict(result)
    rejected['verdicts'][0]['accepted']=False
    rejected['verdicts'][0]['reason']='The source explanation omits a material qualification.'
    with pytest.raises(ValueError):
        review_retained_analysis(gateway([rejected]),result)
    assert not review_complete(result)


def test_duplicate_proof_serializes_once_without_losing_literal_evidence():
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage
    _,selection=paraphrased()
    page=selection.decisions[0].page
    page.context_evidence=[page.source_context[0].quote]
    serialized=page.model_dump(mode='json')
    assert serialized['context_evidence']==[]
    restored=RetainedPage.model_validate(serialized)
    assert restored.all_context_evidence==page.all_context_evidence


@pytest.mark.parametrize('description',[
    'reports an unbound increase of 12%',
    'reports an unbound amount of RMB 12 million',
    'reports an unbound count of twelve units',
])
def test_source_context_metadata_cannot_authorize_visible_quantities(description):
    result,selection=paraphrased()
    selection.decisions[0].page.source_context[0].description=description
    from adaptive_document_agent.agent.reported_source_context import qualified_source_statement
    page=selection.decisions[0].page
    text=page.message+' '+qualified_source_statement(page.source_context[0])
    _,parts=reported_source_components(text,page.all_context_evidence,periods=['FY2023','FY2025'],
                                       declared=page.source_context)
    assert parts==[]
    with pytest.raises(AuthoredPageErrors):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)


def test_declared_context_still_rejects_nonliteral_source_proof_and_wrong_primary_direction():
    result,selection=paraphrased()
    selection.decisions[0].page.source_context[0].quote.text='Invented source proof, absent from the original.'
    with pytest.raises(AuthoredPageErrors,match='literal quote'):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)
    result,selection=paraphrased()
    selection.decisions[0].page.message='Revenue declined from FY2023 to FY2025.'
    with pytest.raises(AuthoredPageErrors):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)


@pytest.mark.parametrize('day,accepted',[('2024-06-30',True),('2024-06-29',False)])
def test_qualitative_context_may_retain_only_bound_literal_calendar_dates(day,accepted):
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy,qualified_source_statement
    quote=BriefQuote(page=2,text='As of June 30, 2024, management reported no material collection issue.')
    item=QualifiedSourceCopy(scope='the reported discussion',
        description=f'reports a collection judgment for receivables outstanding at {day}',quote=quote)
    text='The source reports levels. '+qualified_source_statement(item)
    _,parts=reported_source_components(text,[quote],periods=['2024-06-30'],declared=[item])
    assert bool(parts)==accepted


def test_literal_causal_speech_is_not_a_calculation_and_still_requires_publication_review():
    from adaptive_document_agent.agent.retained_analysis_review import review_complete,review_retained_analysis
    result,selection=reported();before=deepcopy(result.observations)
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete original source selection.')]),result)
    result.presentation_plan=retained.compile_retained_analysis(result)
    slide=next(s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    assert slide.message=='The source reports revenue.'
    assert QUOTE in slide.bullets[1] and slide.bullet_observation_ids[1]==[]
    assert slide.source_pages==[234,235] and result.observations==before
    assert slide.id in bound_authored_slide_ids(result,result.presentation_plan)
    assert not review_complete(result)
    review_retained_analysis(gateway([verdict(result)]),result)
    assert review_complete(result)
    result.document.pages[-1].text='Different source wording.'
    assert not review_complete(result)


@pytest.mark.parametrize('text',[
    'The source states: "'+QUOTE.replace('decrease','increase',1)+'"',
    'For Revenue decreased from FY2023 to FY2025, the source states: "'+QUOTE+'"',
    'For RMB 1,250, the source states: "'+QUOTE+'"',
    'For FY2099 to FY2100, the source states: "'+QUOTE+'"',
    'The source states: "The amount increased by 12%."',
    'The source states: "The amount increased by RMB 12 million."',
])
def test_unbound_quotes_quantities_and_predicates_in_the_scope_keep_normal_checks(text):
    main,contexts=reported_source_components('Revenue is reported. '+text,
        [BriefQuote(page=235,text=QUOTE)],periods=['FY2023','FY2025'])
    assert not contexts and main=='Revenue is reported. '+text


def test_a_quote_cannot_replace_an_entire_analysis_page():
    text='The source states: "'+QUOTE+'"'
    assert reported_source_components(text,[BriefQuote(page=235,text=QUOTE)])==(text,[])


@pytest.mark.parametrize('words,labels,accepted',[
    ('Revenue from four-axis devices increased with market demand.',['Four-axis devices ASP'],True),
    ('Revenue from four-axis devices increased with market demand.',['Device ASP'],False),
    ('All loans were repayable within one year on demand.',[],True),
    ('The source classifies inventories aged more than two years.',[],True),
    ('The measured duration increased by one year.',[],False),
    ('The measured level increased by twelve units.',[],False),
    ('The measured level increased by one million.',[],False),
])
def test_literal_categories_and_duration_conditions_are_distinct_from_measured_quantities(words,labels,accepted):
    text='The source reports levels. The source states: "'+words+'"'
    main,parts=reported_source_components(text,[BriefQuote(page=235,text=words)],labels=labels)
    assert bool(parts)==accepted
    assert main==('The source reports levels.' if accepted else text)


def test_category_labels_keep_their_original_row_binding():
    from adaptive_document_agent.agent.reported_source_context import observation_context_labels
    labels=observation_context_labels([dict(metric_original='ASP',dimensions={'category':'Four-axis devices'})])
    assert labels==['ASP','Four-axis devices']


@pytest.mark.parametrize('mutation',['changed_quote','unbound_empty_bullet'])
def test_empty_row_scope_requires_the_exact_source_bound_compiled_context(mutation):
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    result,selection=reported()
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic source selection.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    if mutation=='changed_quote':
        slide.bullets[1]=slide.bullets[1].replace('decrease','increase',1)
    else:
        slide.bullets.append('Another unbound statement.')
        slide.bullet_observation_ids.append([])
    with pytest.raises(ValueError,match='bullet evidence must use retained'):
        PresentationPlanValidator().validate(plan,result)


@pytest.mark.parametrize('numeric',[
    'Revenue was RMB 999,999 thousand.',
    'Revenue declined from FY2023 to FY2025.',
])
def test_supported_context_cannot_hide_a_bad_numeric_or_directional_main_claim(numeric):
    result,selection=reported()
    page=selection.decisions[0].page
    page.message=page.message.replace('The source reports revenue.',numeric)
    with pytest.raises(AuthoredPageErrors):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)


def test_a_quantitative_quotation_does_not_gain_an_empty_numeric_scope():
    result,selection=reported()
    bad='Revenue declined from FY2023 to FY2025.'
    result.document.pages[-1].text=bad
    page=selection.decisions[0].page
    page.context_evidence=[BriefQuote(page=235,text=bad)]
    page.message='The source reports revenue. The source states: "'+bad+'"'
    with pytest.raises(AuthoredPageErrors):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)


def test_local_copy_repair_replaces_owned_context_and_preserves_appended_assurance(monkeypatch):
    from tests.test_live_publication_repair import measured
    from adaptive_document_agent.agent.retained_analysis_review import review_retained_analysis,review_complete
    measured(monkeypatch)
    result,selection=reported()
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic source selection.')]),result)
    result.presentation_plan=retained.compile_retained_analysis(result)
    slide=next(s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    slide.bullets.append('Additional source assurance remains unmarked.')
    slide.bullet_observation_ids.append(list(slide.observation_ids))
    iid=slide.insight_ids[0]
    rejected=verdict(result)
    rejected['verdicts'][0]['accepted']=False
    revised=selection.decisions[0].page.model_copy(update=dict(message=(
        'The company reports revenue. For FY2023 to FY2025, the source states: "'+QUOTE+'"')))
    llm=gateway([rejected,dict(pages={iid:revised.model_dump()}),verdict(result)])
    review_retained_analysis(llm,result,repair_copy=True)
    assert review_complete(result)
    assert len(slide.bullets)==3 and QUOTE in slide.bullets[1]
    assert slide.bullets[-1]=='Additional source assurance remains unmarked.'
    assert slide.bullet_observation_ids[1]==[]
