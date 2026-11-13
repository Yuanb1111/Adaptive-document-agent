"""Source-only timing is distinct from numeric observations and calculations."""
import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_page_sources import validate_authored_pages,AuthoredPageErrors
from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
from adaptive_document_agent.agent.source_context_periods import mask_source_periods
from adaptive_document_agent.models.executive_brief import BriefQuote
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_reported_source_context import paraphrased
from tests.test_retained_analysis_v216 import gateway

PROOF=('During 2018, 2019 and the three months ended March 31, 2020, '
       'the source describes prolonged losses as indicating impairment.')


def prepared(scope='2018, 2019 and the three months ended March 31, 2020',
             description='describes prolonged losses during 2018, 2019 and the three months ended March 31, 2020 as indicating impairment'):
    result,selection=paraphrased()
    page=selection.decisions[0].page
    result.document.pages[-1].text=PROOF
    page.source_context=[QualifiedSourceCopy(scope=scope,description=description,
        quote=BriefQuote(page=235,text=PROOF))]
    return result,selection


def test_literal_annual_and_months_ended_scope_can_compile_without_numeric_rows():
    result,selection=prepared()
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic source coverage.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    assert '2018' in slide.bullets[1] and '2020-03-31' in slide.bullets[1]
    assert slide.bullet_observation_ids[1]==[]
    assert PresentationPlanValidator().validate(plan,result) is plan


@pytest.mark.parametrize('scope,description',[
    ('2017, 2019 and the three months ended March 31, 2020','describes prolonged losses as indicating impairment'),
    ('2018 and 2019','describes prolonged losses during 2017 as indicating impairment'),
    ('the reported discussion','describes losses during the six months ended March 31, 2020'),
    ('the reported discussion','describes losses during the three months ended March 30, 2020'),
    ('the reported discussion','reports a loss of 2018 units'),
    ('the reported discussion','reports a measured increase of three months'),
    ('the reported discussion','describes losses in FY2018'),
])
def test_wrong_dates_durations_labels_and_measured_values_remain_rejected(scope,description):
    result,selection=prepared(scope,description)
    with pytest.raises(AuthoredPageErrors):
        validate_authored_pages(selection,retained.selection_context(result,source_authoring=True),result)


def test_amount_resembling_year_cannot_lend_source_temporal_authority():
    assert '2018' in mask_source_periods('describes a decline during 2018.',
                                      'The source reports 2018 units.')
    assert '2018 units' in mask_source_periods('reports 2018 units.',PROOF)


@pytest.mark.parametrize('month,accepted',[('December 2023',True),('November 2023',False),('December 2022',False)])
def test_month_year_may_only_project_an_exact_bound_calendar_date(month,accepted):
    masked=mask_source_periods('attributes the '+month+' balance to demand.',
        'Management discusses demand.',periods=['2023-12-31'])
    assert ('2023' not in masked and '2022' not in masked)==accepted


@pytest.mark.parametrize('word,accepted',[('two',True),('three',False)])
def test_worded_older_than_category_boundary_needs_its_exact_literal_source(word,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='The source says inventories with an age of more than 2 years generally aligned with expectations.'
    item=QualifiedSourceCopy(scope='the reported discussion',
        description=f'describes the older-than-{word}-year category as generally aligned with expectations',
        quote=BriefQuote(page=1,text=proof))
    _,parts=reported_source_components('The source reports levels. '+qualified_source_statement(item),
        [item.quote],declared=[item])
    assert bool(parts)==accepted


@pytest.mark.parametrize('phrase,accepted',[
    ('the next 12 months from the publication date',True),
    ('the next twelve months from the publication date',True),
    ('the next 18 months from the publication date',False),
    ('the next 12 years from the publication date',False),
    ('working capital of 12 units',False),
    ('a measured increase of 12 months',False),
])
def test_future_source_condition_does_not_authorize_other_durations_or_measured_values(phrase,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='The Directors considered the available resources sufficient for the next 12 months from the publication date.'
    item=QualifiedSourceCopy(scope='the liquidity discussion',
        description='describes the Directors view on '+phrase,quote=BriefQuote(page=1,text=proof))
    _,parts=reported_source_components('The source reports balances. '+qualified_source_statement(item),
        [item.quote],declared=[item])
    assert bool(parts)==accepted


def test_horizon_mask_does_not_rewrite_other_worded_conditions():
    from adaptive_document_agent.agent.source_context_periods import mask_source_horizons
    text='the next twelve months and the older-than-two-year category'
    masked=mask_source_horizons(text,'The source discusses the next 12 months.')
    assert 'twelve' not in masked and 'older-than-two-year' in masked
