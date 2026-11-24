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


@pytest.mark.parametrize('description,scope,extra_proof,accepted', [
    ('describes inventory held at June 30 as subsequently sold.',
     '2024-06-30 and 2024-10-31','',True),
    ('describes inventory held at June 30 as subsequently sold.',
     '2024-10-31','',False),
    ('describes inventory held at June 30 as subsequently sold.',
     '2024-06-30 and 2024-10-31',' The company also held inventory on June 30, 2023.',False),
    ('describes inventory held at June 29 as subsequently sold.',
     '2024-06-30 and 2024-10-31','',False),
    ('reports inventory at June 30 units.',
     '2024-06-30 and 2024-10-31','',False),
])
def test_partial_calendar_reference_needs_one_exact_proved_date_in_same_scope(
        description,scope,extra_proof,accepted):
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy,qualified_source_statement

    quote=BriefQuote(page=1,text='Inventory held at June 30, 2024 was subsequently sold by October 31, 2024.'
                               +extra_proof)
    item=QualifiedSourceCopy(scope=scope,description=description,quote=quote)
    statement=qualified_source_statement(item)
    _,accepted_parts=reported_source_components('The source reports balances. '+statement,[quote],
        periods=['2024-06-30','2024-10-31'],declared=[item])
    assert bool(accepted_parts) is accepted


def test_overlong_source_description_splits_only_complete_verb_led_sentences_losslessly():
    from adaptive_document_agent.agent.reported_source_context import split_overlong_source_descriptions
    scope='FY2023 to FY2025'
    quote={'page':235,'text':QUOTE}
    sentences=[
        'Describes '+('the effect of customer demand on the reported business operations, while preserving the stated conditions and management context '*2)+'.',
        'Attributes '+('the change to product mix and distribution arrangements, without stating a measured amount or calculated comparison '*2)+'.',
        'Notes '+('that the discussion concerns the same reporting scope and retains the source qualification in full '*2)+'.',
    ]
    description=' '.join(sentences)
    assert len(description)>700 and all(len(sentence)<=700 for sentence in sentences)
    original=[{'scope':scope,'description':description,'quote':quote}]
    split=split_overlong_source_descriptions(original)
    assert [item['description'] for item in split]==sentences
    assert all(item['scope']==scope and item['quote']==quote for item in split)
    assert ' '.join(item['description'] for item in split)==description


def test_overlong_company_attributed_description_splits_with_explicit_company_subject():
    from adaptive_document_agent.agent.reported_source_context import split_overlong_source_descriptions
    scope='2021 to 2024'
    quote={'page':311,'text':'The company describes the market and attributes the change to product demand.'}
    clauses=[
        'The company describes '+('the market conditions and the source-defined effect on its operating results '*3)+'.',
        'It attributes '+('the movement to the stated product mix and customer demand conditions '*3)+'.',
        'It attributes '+('the related development to the source-described overseas supply-chain change '*3)+'.',
    ]
    description=' '.join(clauses)
    assert len(description)>700 and all(len(clause)<=700 for clause in clauses)
    original=[{'scope':scope,'description':description,'quote':quote}]
    split=split_overlong_source_descriptions(original)
    assert [item['description'] for item in split]==[
        'Reports that the company describes '+clauses[0].removeprefix('The company describes '),
        'Reports that the company attributes '+clauses[1].removeprefix('It attributes '),
        'Reports that the company attributes '+clauses[2].removeprefix('It attributes '),
    ]
    assert all(len(item['description'])<=700 for item in split)
    assert all(item['scope']==scope and item['quote']==quote for item in split)


def test_long_attributed_description_keeps_complete_statement_groups_and_possessives():
    from adaptive_document_agent.agent.reported_source_context import split_overlong_source_descriptions

    sentences=[
        'Describes the company’s loss and continuing investment, '+('including the source’s original conditions, '*8)+'during the period.',
        'Prolonged losses indicated impairment. Testing covered '+('assets with the stated conditions, '*8)+'using the approved basis.',
        'The test found the assets’ recoverable amount exceeded the stated carrying amount.',
    ]
    original=' '.join(sentences)
    quote={'page':4,'text':'Literal source explains the test and its conclusion.'}
    continuation={'page':5,'text':'Literal continuation describes the stated conditions.'}
    items=[dict(scope='the reporting period',description=original,quote=quote,continuation_quotes=[continuation])]
    assert len(original)>700
    result=split_overlong_source_descriptions(items)
    assert len(result)==2 and all(len(item['description'])<=700 for item in result)
    assert ' '.join(item['description'].removeprefix('Reports the following. ') for item in result)==original
    assert all(item['scope']==items[0]['scope'] and item['quote']==quote
               and item['continuation_quotes']==[continuation] for item in result)


def test_overlong_description_keeps_dependent_sentence_with_its_antecedent():
    from adaptive_document_agent.agent.reported_source_context import split_source_description

    first='Describes the reporting context, '+('including the stated conditions, '*13)+'during the period.'
    assessment='Management says it reviewed the source evidence, '+('including its stated factors, '*11)+'before responding.'
    dependent='These judgments concern the assessment of the original balance.'
    original=' '.join((first,assessment,dependent))
    assert len(original)>700
    assert split_source_description(original)==[first,'Reports the following. '+assessment+' '+dependent]


@pytest.mark.parametrize('description', [
    'It describes '+('the same source discussion in detail '*24)+'. The company reports a related effect.',
    'The company describes '+('the same source discussion in detail '*24)+'. They attribute another effect.',
    'The company describes '+('the same source discussion in detail '*24)+'. It caused another effect.',
    'The company describes '+('the same source discussion in detail '*24)+'. It attributes that it changed.',
])
def test_overlong_company_attribution_requires_unambiguous_speaker_and_reporting_verbs(description):
    from adaptive_document_agent.agent.reported_source_context import split_overlong_source_descriptions
    items=[{'scope':'the reported discussion','description':description,
            'quote':{'page':1,'text':QUOTE}}]
    assert len(description)>700
    assert split_overlong_source_descriptions(items) is items


@pytest.mark.parametrize('description,extra,count',[
    ('Describes '+('a supported discussion. '*36)+'A separate sentence without an allowed verb.',{},1),
    ('Describes the phrase "a quoted sentence. Still quoted" and its meaning. '+('Notes '+('another supported subject. '*27)),{},1),
    ('Describes '+('a complete supported point. '*36),{'unexpected':'preserve'},1),
])
def test_overlong_source_description_leaves_ambiguous_or_extended_items_unchanged(description,extra,count):
    from adaptive_document_agent.agent.reported_source_context import split_overlong_source_descriptions
    item={'scope':'FY2023','description':description,'quote':{'page':1,'text':QUOTE},**extra}
    values=[item]
    result=split_overlong_source_descriptions(values)
    assert result is values and len(result)==count


def test_overlong_source_description_respects_existing_item_capacity():
    from adaptive_document_agent.agent.reported_source_context import split_overlong_source_descriptions
    items=[{'scope':f'FY202{i}','description':'Notes a source qualification.',
            'quote':{'page':1,'text':QUOTE}} for i in range(7)]
    items[0]['description']='Describes '+('a fully supported source point. '*18)+'. Attributes '+('a separate supported point. '*18)
    assert len(items[0]['description'])>700
    assert split_overlong_source_descriptions(items) is items


def test_overlong_source_description_does_not_split_abbreviation_punctuation():
    from adaptive_document_agent.agent.reported_source_context import split_overlong_source_descriptions
    item={'scope':'FY2023','description':('Describes U.S. market conditions. '*24)+
          'Attributes a separate source qualification.','quote':{'page':1,'text':QUOTE}}
    values=[item]
    assert len(item['description'])>700
    assert split_overlong_source_descriptions(values) is values


def test_each_overlong_continuation_splits_losslessly_without_reordering_pages():
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
    from adaptive_document_agent.services.source_quotes import normalize_quote
    long='The source explains a complete condition and its related qualification. '*48
    short='The source adds a separate continuation on this page.'
    item=QualifiedSourceCopy.model_validate(dict(scope='the reported discussion',
        description='describes a source condition and qualification',
        quote={'page':1,'text':'The source introduces the discussion.'},
        continuation_quotes=[{'page':2,'text':long},{'page':3,'text':short}]))
    assert [proof.page for proof in item.proof_quotes]==[1,2,2,3]
    assert all(len(proof.text)<=1800 for proof in item.proof_quotes)
    assert normalize_quote(' '.join(proof.text for proof in item.continuation_quotes[:2]))==normalize_quote(long)
    assert item.continuation_quotes[-1].text==short


def test_overlong_nested_continuation_is_split_after_conflict_check():
    from pydantic import ValidationError
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
    from adaptive_document_agent.services.source_quotes import normalize_quote
    long='The source explains a complete condition and its related qualification. '*48
    raw=dict(scope='the reported discussion',description='describes a source condition',quote={
        'page':1,'text':'The source introduces the discussion.',
        'continuation_quotes':[{'page':2,'text':long}]})
    item=QualifiedSourceCopy.model_validate(raw)
    assert [proof.page for proof in item.proof_quotes]==[1,2,2]
    assert normalize_quote(' '.join(proof.text for proof in item.continuation_quotes))==normalize_quote(long)
    conflict={**raw,'continuation_quotes':[{'page':3,'text':'A conflicting continuation.'}]}
    with pytest.raises(ValidationError):
        QualifiedSourceCopy.model_validate(conflict)


def test_overlong_continuations_do_not_expand_existing_three_item_capacity():
    from pydantic import ValidationError
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
    long='The source explains a complete condition and its related qualification. '*48
    raw=dict(scope='the reported discussion',description='describes a source condition',
        quote={'page':1,'text':'The source introduces the discussion.'},
        continuation_quotes=[{'page':2,'text':long},{'page':3,'text':long}])
    with pytest.raises(ValidationError):
        QualifiedSourceCopy.model_validate(raw)


@pytest.mark.parametrize('description,proof,accepted', [
    ('describes six-axis cobot revenue as part of the product offering',
     'The source discusses revenue from six-axis cobot products.',True),
    ('describes six-axis cobots revenue as part of the product offering',
     'The source discusses revenue from six-axis cobot products.',True),
    ('describes six-axis and integrated cobots as drivers',
     'The source discusses six-axis cobots and integrated cobots.',True),
    ('describes lower six-axis and four-axis cobot margins',
     'The source discusses lower margins for six-axis cobots and four-axis cobots.',True),
    ('describes six-axis and integrated cobots as drivers',
     'The source discusses six-axis cobots and integrated robots.',False),
    ('describes lower six-axis and four-axis cobot margins',
     'The source discusses lower margins for six-axis cobots and four-axis robots.',False),
    ('describes six-axis and integrated cobots valued at RMB 9 million',
     'The source discusses six-axis cobots and integrated cobots.',False),
    ('describes seven-axis cobot revenue as part of the product offering',
     'The source discusses revenue from six-axis cobot products.',False),
    ('describes six-axis robot revenue as part of the product offering',
     'The source discusses revenue from six-axis cobot products.',False),
    ('describes six axis cobot revenue as part of the product offering',
     'The source discusses revenue from six-axis cobot products.',False),
    ('describes six-axis Model-X revenue as part of the product offering',
     'The source discusses revenue from six-axis cobot products.',False),
    ('describes six-axis cobot revenue of RMB 30 million',
     'The source discusses revenue from six-axis cobot products.',False),
    ('describes six-month cobot revenue as part of the product offering',
     'The source discusses revenue from six-axis cobot products.',False),
])
def test_worded_axis_category_needs_exact_modifier_and_source_product_noun(
        description,proof,accepted):
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy,qualified_source_statement
    quote=BriefQuote(page=1,text=proof)
    item=QualifiedSourceCopy(scope='the product discussion',description=description,quote=quote)
    statement=qualified_source_statement(item)
    _,parts=reported_source_components('The source reports product revenue. '+statement,
        [quote],declared=[item])
    assert bool(parts) is accepted


@pytest.mark.parametrize('description,proof,accepted', [
    ('describes the inventory measurement basis under IAS 2',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',True),
    ('describes IAS 2 lower-of-cost/NRV tests',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',True),
    ('describes IAS 2: lower cost/NRV; tests assess recoverability',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',True),
    ('describes IAS 2: lower cost/NRV; inventories aged 30 days',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',False),
    ('describes IAS 2 lower-of-cost/NRV tests',
     'The source states its measurement method in accordance with IAS 3.',False),
    ('reports that IAS 36 testing found no impairment',
     'In accordance with IAS 36, we performed impairment tests at each period-end.',True),
    ('reports that IAS 36 testing found no impairment in 12 assets',
     'In accordance with IAS 36, we performed impairment tests at each period-end.',False),
    ('reports that IAS 2 testing found no impairment',
     'In accordance with IAS 36, we performed impairment tests at each period-end.',False),
    ('describes IAS 2 reporting sites',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',False),
    ('describes the inventory measurement basis under IAS 3',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',False),
    ('describes inventory aged under IAS 2 years',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',False),
    ('describes the inventory measurement basis under IAS 2 with RMB 30 million',
     'Inventories are stated at the lower of cost and net realizable value in accordance with IAS 2.',False),
])
def test_literal_accounting_standard_identifier_is_not_a_quantity(
        description,proof,accepted):
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy,qualified_source_statement
    quote=BriefQuote(page=332,text=proof)
    item=QualifiedSourceCopy(scope='the inventory accounting discussion',
        description=description,quote=quote)
    statement=qualified_source_statement(item)
    _,parts=reported_source_components('The source reports inventory. '+statement,
        [quote],declared=[item])
    assert bool(parts) is accepted


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


def test_source_context_partitive_one_of_is_qualitative_but_explicit_count_is_not():
    from adaptive_document_agent.agent.reported_source_context import (
        QualifiedSourceCopy,qualified_source_statement)
    quote=BriefQuote(page=340,text=(
        'In the six months ended June 30, 2024, changes in working capital that negatively '
        'affected operating cash flow primarily included an increase in inventories of '
        'RMB23.1 million, partially offset by changes that positively affected operating '
        'cash flow, primarily a decrease in trade and bill receivables of RMB9.7 million.'))
    description=('describes inventory growth as one of the working-capital changes that '
        'negatively affected operating cash flow')
    item=QualifiedSourceCopy(scope='2024-06-30',description=description,quote=quote)
    statement=qualified_source_statement(item)
    _,parts=reported_source_components('The source reports cash flow. '+statement,
        [quote],periods=['2024-06-30'],declared=[item])
    assert parts==[statement]

    for count_phrase in ('one of two','one of the two','one of those 3'):
        quantified=item.model_copy(update={'description':(
            f'describes inventory growth as {count_phrase} working-capital changes that '
            'negatively affected operating cash flow')})
        quantified_statement=qualified_source_statement(quantified)
        _,parts=reported_source_components('The source reports cash flow. '+quantified_statement,
            [quote],periods=['2024-06-30'],declared=[quantified])
        assert parts==[]


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


@pytest.mark.parametrize('prefix,accepted',[('p. 3: ',True),('Page 3: ',True),
    ('p. 4: ',False),('p. 3 and p. 4: ',False)])
def test_only_a_redundant_exact_proof_page_can_leave_visible_source_copy(prefix,accepted):
    from adaptive_document_agent.agent.reported_source_context import (
        QualifiedSourceCopy, qualified_source_statement, reported_source_components)
    from adaptive_document_agent.models.executive_brief import BriefQuote

    proof=BriefQuote(page=3,text='Management considered the provision adequate.')
    item=QualifiedSourceCopy(scope='the source discussion',
        description=prefix+'Management considered the provision adequate.',quote=proof)
    statement=qualified_source_statement(item)
    _,parts=reported_source_components('Reported levels. '+statement,[proof],declared=[item])
    assert bool(parts)==accepted
    assert item.description.startswith(prefix) and item.quote==proof
    if accepted:
        assert statement=='For the source discussion, the source reports that management considered the provision adequate.'
