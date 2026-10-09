"""Generic regressions reproduced by the two downloaded prospectus reviews."""

import json
import pytest

from adaptive_document_agent.agent.brief_native_quantities import native_quantity_options
from adaptive_document_agent.agent.topic_reference_binding import bind_topic_references
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.document_model import DocumentIndex, period_sort_key
from adaptive_document_agent.extraction.borderless_layout import SourceLine
from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
from adaptive_document_agent.extraction.period_header_geometry import geometric_periods
from adaptive_document_agent.models import ChartPlan, PresentationSlide, PresentationTopic, PresentationTopicSelection, ValidationIssue
from adaptive_document_agent.services.presentation_key_figures import _figure
from adaptive_document_agent.services.presentation_chart_annotation import chart_change_annotation
from adaptive_document_agent.services.presentation_scope import scope_items
from adaptive_document_agent.services.single_metric_analysis import single_metric_analysis
from tests.test_pptx_export import _result
from tests.test_single_metric_enrichment import series
from tests.test_brief_table_context import table_result
from tests.test_presentation_identity_contents import _deck


def line(text, left, right):
    return SourceLine(text, [(0, len(text), left, right)])


@pytest.mark.parametrize('count, word', [(2, 'two'), (4, 'four'), (5, 'five'), (7, 'seven'), (8, '8'), (10, 'ten'), (11, 'eleven')])
def test_arbitrary_month_duration_scopes_last_column_by_geometry(count, word):
    years = SourceLine('2022 2023 2024 2025', [(0,4,10,30),(5,9,50,70),(10,14,90,110),(15,19,130,150)])
    headers = [line('Year ended', 35,85), line(f'{word} months', 125,155)]
    assert geometric_periods(headers, years, 4) == ['FY2022','FY2023','FY2024',f'{count}M2025']
    assert BorderlessTableExtractor._expand_periods(['2022','2023','2024','2025'],4,
        ['Year ended December 31,',f'{word} months ended May 31,','2022 2023 2024 2025'],2)==[None]*4


def test_five_month_comparative_header_keeps_prior_interim_distinct():
    periods=BorderlessTableExtractor._expand_periods(['2022','2023','2024','2024','2025'],5,
        ['Year ended December 31, Five months ended May 31,','2022 2023 2024 2024 2025'],1)
    assert periods==['FY2022','FY2023','FY2024','5M2024','5M2025']
    assert BorderlessTableExtractor._period_from_line('Five months ended May 31, 2025')=='5M2025'
    assert BorderlessTableExtractor._context_label(['OPERATING STATISTICS','Five months','ended','Year ended December 31, May 31,'],4)=='OPERATING STATISTICS'


def test_date_superheader_does_not_become_a_flow_when_another_tier_says_months():
    years=SourceLine('2022 2023 2024 2025',[(0,4,10,30),(5,9,50,70),(10,14,90,110),(15,19,130,150)])
    headers=[line('Five months',125,155),SourceLine('As of December 31, May 31,',
        [(0,18,35,85),(19,26,125,155)])]
    assert geometric_periods(headers,years,4)==['2022-12-31','2023-12-31','2024-12-31','2025-05-31']


def test_mixed_fiscal_and_five_month_amounts_never_generate_growth_or_cagr():
    observations=series((45523,52962,86631,61038),('FY2022','FY2023','FY2024','5M2025'))
    chart=ChartPlan(id='costs',title='Costs',question='How do costs compare?',chart_type='bar',observation_ids=[o.id for o in observations])
    assert single_metric_analysis(observations) is None
    assert _figure(chart,{o.id:o for o in observations},'Costs') is None
    assert chart_change_annotation(chart,DocumentIndex(observations))==''
    matched=single_metric_analysis(series(periods=('5M2023','5M2024','5M2025')))
    assert matched.cagr is None and all(change.is_yoy for change in matched.changes)


def test_date_index_sorts_may_before_august_and_preserves_assurance_marker():
    assert sorted(['31 Aug 2025*','31 May 2025','31 Dec 2024'],key=period_sort_key)==[
        '31 Dec 2024','31 May 2025','31 Aug 2025*']


def test_exact_omitted_namespace_retains_question_and_never_guesses_a_reference():
    result=_result(); _,lookup=series_directory(result); exact=next(iter(lookup))
    topic=PresentationTopic(id='chosen',title='Reported movement',question='How did reported values move?',
        rationale='Comparable source evidence.',series_ids=[exact.removeprefix('presentation_series_')])
    selection=PresentationTopicSelection(topics=[topic])
    bind_topic_references(selection,lookup,result)
    assert topic.series_ids==[exact]
    PresentationTopicSelector._validate(selection,lookup)
    audit=json.loads(result.validation_warnings[-1].message)
    assert audit['bindings'][0]['resolved']==exact
    for invalid in ('made-up', exact[-8:]):
        topic.series_ids=[invalid]
        bind_topic_references(selection,lookup,result)
        assert topic.series_ids==[invalid]
        with pytest.raises(ValueError,match='unknown'):
            PresentationTopicSelector._validate(selection,lookup)
    ambiguous={'presentation_series_same':[], 'presentation_composition_same':[]}
    topic.series_ids=['same']; bind_topic_references(selection,ambiguous,result)
    assert topic.series_ids==['same']


def test_scope_reflects_recovered_renderer_evidence_and_keeps_real_omissions():
    from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
    result=_result(); result.presentation_plan=PresentationPlanRecovery().fallback(result,validate=False)
    _,lookup=series_directory(result); sid,members=next(iter(lookup.items()))
    for topic_id,ids in [('shown',[sid.removeprefix('presentation_series_')]),('missing',['unknown'])]:
        topic=PresentationTopic(id=topic_id,title=topic_id,question='What changed?',rationale='Review',series_ids=ids)
        result.validation_warnings.append(ValidationIssue(code='presentation_topic_validation',stage='presentation',
            message=json.dumps({'phase':'initial','topic':topic.model_dump()})))
    result.presentation_export_trace=[{'observation_ids':[o.id for o in members]}]
    titles=[i.title for i in scope_items(result)]
    assert 'Not covered: shown' not in titles and 'Not covered: missing' in titles
    result.presentation_export_trace=[{'observation_ids':[members[0].id]}]
    assert 'Partially covered: shown' in [i.title for i in scope_items(result)]


def test_agenda_orders_operating_flow_after_every_company_page():
    from adaptive_document_agent.services.pptx_export import _add_planned_contents
    deck=_deck()
    _add_planned_contents(deck,[PresentationSlide(id='overview',slide_type='company_overview',title='Overview'),
        PresentationSlide(id='products',title='Products',slide_type='company_overview',section_title='Products'),
        PresentationSlide(id='summary',title='Executive Summary',slide_type='executive_summary')],include_value_chain=True)
    assert [s.text for s in deck.slides[0].shapes if s.name.startswith('contents:entry:')]==[
        'Company Overview','Products','How the business operates','Executive Summary']


def test_optional_flow_does_not_split_a_long_heading_word():
    from tests.test_presentation_value_chain import _company
    from adaptive_document_agent.services.presentation_value_chain import can_render_value_chain
    company,_=_company()
    company.value_chain.extend([company.value_chain[0].model_copy(deep=True) for _ in range(2)])
    company.value_chain[2].label='Commercialization'
    assert not can_render_value_chain(company,13.333)


def test_repair_receives_native_signed_values_but_cannot_authorize_conversion():
    result,brief=table_result(); original=brief.model_dump(mode='json')
    original['items'][0]['text']='Programme fees were USD 1.5 million.'
    excerpts={p.page_number:p.text for p in result.document.pages}
    options=native_quantity_options(original,{0:[]},result,excerpts)['item_0']
    assert {'currency':'us$','signed_coefficient':'1475','source_scale':'thousand','literal_basis':['']} in options
    assert not any(o['source_scale']=='million' for o in options)
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    brief.items[0].text=original['items'][0]['text']
    assert validate_executive_brief(brief,result)


def test_complete_composition_does_not_use_a_single_colon_qualified_component():
    from tests.test_composition_scope_headings import matrix
    from adaptive_document_agent.services.presentation_labels import composition_heading
    observations,chart=matrix(metric='Current assets',categories=('Inventories','Cash'))
    assert composition_heading('Current assets: Inventories',chart,observations)=='Current assets'
    assert composition_heading('Reported measures',chart,observations)=='Current assets'


def test_row_footnote_is_literal_and_never_inherited_from_another_table_or_note():
    from adaptive_document_agent.models import DocumentPage, ExtractedTable
    from adaptive_document_agent.services.source_row_qualifications import source_row_qualifications
    from adaptive_document_agent.services.presentation_context_notes import slide_context_notes
    result=_result(); obs=series(metric='Cash operating costs')
    quote='The measure excludes non-cash personnel expenses and working capital adjustments.'
    result.document.pages=[DocumentPage(page_number=3,text='Notes:\n(1) '+quote+' Further details follow.',
        tables=[ExtractedTable(table_id='costs',page=3,raw_body_lines=['Cash operating costs(1) 100 120 144'])])]
    for item in obs:
        item.evidence[0].table_id='costs'; item.evidence[0].row_label='Cash operating costs'
    notes=source_row_qualifications(obs,result.document)
    assert len(notes)==1 and notes[0]['text']==quote and notes[0]['page']==3
    chart=ChartPlan(id='costs',title='Cash costs',question='What is included?',chart_type='bar',observation_ids=[o.id for o in obs])
    assert quote in slide_context_notes(result,PresentationSlide(id='costs',slide_type='analysis',title='Costs'),
        [chart],DocumentIndex(obs),definitions=[])
    result.document.pages[0].text+='\n(1) A competing note is ambiguous.'
    assert source_row_qualifications(obs,result.document)==[]
    result.document.pages[0].text='(2) '+quote
    assert source_row_qualifications(obs,result.document)==[]


def test_native_scale_repair_keeps_the_lead_and_validates_the_final_patch():
    from adaptive_document_agent.agent.brief_item_repair import generate_with_item_repair
    from adaptive_document_agent.services.executive_brief import validate_executive_brief
    from tests.test_executive_brief import gateway
    result,correct=table_result(); original=correct.model_dump(mode='json')
    original['items'][0]['text']='Programme fees were USD 1.5 million.'
    g,client=gateway([original,{'item_0':correct.items[0].model_dump(mode='json')}])
    brief=generate_with_item_repair(g,[{'role':'system','content':'Summarize the evidence.'}],result=result,
        excerpts={p.page_number:p.text for p in result.document.pages},topics=[],source_context={})
    assert len(client.calls)==2 and brief.items[0].text==correct.items[0].text
    assert not validate_executive_brief(brief,result)
    assert 'source_native_money_options' in client.calls[1][-1]['content']
    assert '1475' in client.calls[1][-1]['content']


def test_unknown_month_duration_does_not_match_a_known_duration_suffix():
    from adaptive_document_agent.extraction.period_header_geometry import MONTH_DURATION
    import re
    for header in ('13 months','twentyfive months','23months'):
        assert re.search(MONTH_DURATION,header,re.I) is None


def test_complete_corroborating_source_view_is_not_labeled_missing():
    from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
    result=_result()
    for observation in result.observations:
        for evidence in observation.evidence:
            evidence.row_label=observation.metric_original
    result.presentation_plan=PresentationPlanRecovery().fallback(result,validate=False)
    _,lookup=series_directory(result); sid,members=next(iter(lookup.items()))
    # Another page repeats the exact same qualified source facts under distinct IDs.
    duplicates=[o.model_copy(deep=True,update={'id':o.id+'_repeated'}) for o in members]
    result.observations.extend(duplicates)
    topic=PresentationTopic(id='shown',title='Shown facts',question='What changed?',rationale='Review',series_ids=[sid])
    result.validation_warnings.append(ValidationIssue(code='presentation_topic_validation',stage='presentation',
        message=json.dumps({'phase':'initial','topic':topic.model_dump(),
                            'source_scopes':{sid:[o.id for o in members]}})))
    result.presentation_export_trace=[{'observation_ids':[o.id for o in duplicates]}]
    assert not any(i.title.endswith('Shown facts') for i in scope_items(result))
    duplicates[0].raw_value='999'
    assert any(i.title=='Partially covered: Shown facts' for i in scope_items(result))
