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


def test_bound_fy_can_stay_separate_from_its_proved_literal_months_ended_window():
    from adaptive_document_agent.agent.reported_source_context import (
        QualifiedSourceCopy,qualified_source_statement,reported_source_components)
    from adaptive_document_agent.agent.source_context_periods import scope_period_feedback

    proof=('The programme was affected for the six months ended June 30, 2024; '
           'its FY2023 annual profile remained relevant.')
    quote=BriefQuote(page=1,text=proof)
    item=QualifiedSourceCopy(scope='FY2023 and six months ended June 30, 2024',
        description='describes operating pressure',quote=quote)
    statement=qualified_source_statement(item)
    _,accepted=reported_source_components(statement+' Reported revenue was 100.',[quote],
        periods=['FY2023'],declared=[item])
    assert accepted==[statement]
    assert scope_period_feedback(item.scope,['FY2023']) is None

    shorthand=QualifiedSourceCopy(scope='FY2023 and 6M2024',
        description='describes operating pressure',quote=quote)
    rejected=qualified_source_statement(shorthand)
    _,accepted=reported_source_components(rejected+' Reported revenue was 100.',[quote],
        periods=['FY2023'],declared=[shorthand])
    assert accepted==[]
    hint=scope_period_feedback(shorthand.scope,['FY2023'])
    assert hint['unbound_scope_period_labels']==['6M2024']

    wrong_window=QualifiedSourceCopy(scope='FY2023 and nine months ended June 30, 2024',
        description='describes operating pressure',quote=quote)
    rejected=qualified_source_statement(wrong_window)
    _,accepted=reported_source_components(rejected+' Reported revenue was 100.',[quote],
        periods=['FY2023'],declared=[wrong_window])
    assert accepted==[]

    snapshot=QualifiedSourceCopy(scope='FY2023 and 2024-06-30',
        description='describes operating pressure',quote=quote)
    rejected=qualified_source_statement(snapshot)
    _,accepted=reported_source_components(rejected+' Reported revenue was 100.',[quote],
        periods=['FY2023'],declared=[snapshot])
    assert accepted==[]


@pytest.mark.parametrize('scope,accepted', [
    ('2021 to 2022',True),
    ('2020 to 2022',False),
])
def test_literal_leading_year_range_masks_both_existing_source_endpoints(scope,accepted):
    proof='Training costs changed from 2021 to 2022 as staffing expanded.'
    masked=mask_source_periods(scope,proof,scope=True)
    assert (not any(char.isdigit() for char in masked)) is accepted


@pytest.mark.parametrize('scope,proof,accepted', [
    ('2023 compared with 2022',
     'Inventory turnover days increased in 2023 compared with 2022.',True),
    ('2022 compared with 2023',
     'Inventory turnover days increased in 2023 compared with 2022.',False),
    ('2023 and 2022',
     'Inventory turnover days increased in 2023 compared with 2022.',False),
    ('2023 compared to 2022',
     'Inventory turnover days increased in 2023 compared with 2022.',False),
    ('2023 compared with 2022',
     'Inventory turnover days increased in 2022 compared with 2023.',False),
    ('RMB 3 million compared with RMB 2 million',
     'The amount was RMB 3 million compared with RMB 2 million.',False),
    ('2023 compared with 2022',
     'Receipts were 2023 compared with 2022 units.',False),
    ('2023 compared with 2022 units',
     'Inventory turnover days increased in 2023 compared with 2022.',False),
])
def test_literal_ordered_year_comparison_requires_exact_source_relation(scope,proof,accepted):
    masked=mask_source_periods(scope,proof,scope=True)
    assert (not any(char.isdigit() for char in masked)) is accepted


def test_literal_ordered_year_comparison_can_be_repeated_in_its_description():
    text='describes higher efficiency in 2023 compared with 2022, partly offset by sourcing costs.'
    proof='Production reached higher cost efficiency in 2023 compared with 2022, partly offset by sourcing costs.'
    assert '2022' not in mask_source_periods(text,proof)
    finite='describes how higher efficiency in 2023 compared with 2022 was partly offset by sourcing costs.'
    assert '2022' not in mask_source_periods(finite,proof)
    assert '2022' in mask_source_periods(finite,'Annual performance in 2022 compared with 2023 was lower.')


@pytest.mark.parametrize('text,proof,accepted', [
    ('Moving production in-house since 2022 contributed to the shift.',
     'Production moved in-house since 2022, and logistics changed.',True),
    ('Moving production in-house since 2022 contributed to the shift.',
     'Production expanded in 2022, and logistics changed.',False),
    ('The shift followed since 2022 units were shipped.',
     'Production moved in-house since 2022, and logistics changed.',False),
])
def test_since_year_followed_by_a_predicate_still_needs_literal_timing(text,proof,accepted):
    assert ('2022' not in mask_source_periods(text,proof)) is accepted


@pytest.mark.parametrize('text,accepted', [
    ('It links 2023 lengthening to demand. Facilities opened in 2023 supported delivery.',True),
    ('It links 2022 lengthening to demand. Facilities opened in 2023 supported delivery.',False),
    ('Explains 2023 growth from demand.',True),
    ('Explains 2022 growth from demand.',False),
    ('Explains 2023 additional facilities.',False),
    ('Notes demand drove the 2023 rise.',True),
    ('Notes demand drove the 2022 rise.',False),
    ('It describes 2023 units for delivery.',False),
    ('It links 2023 vehicles to demand.',False),
])
def test_owned_event_years_bind_without_masking_measured_counts(text,accepted):
    proof='Turnover increased in 2023 as demand rose. Facilities opened in 2023 for local delivery.'
    masked=mask_source_periods(text,proof)
    assert (not any(char.isdigit() for char in masked)) is accepted


@pytest.mark.parametrize('scope,phrase,accepted', [
    ('six months ended June 30, 2023 to six months ended June 30, 2024','six-month comparison',True),
    ('six months ended June 30, 2023 to six months ended June 30, 2024','nine-month comparison',False),
    ('six months ended June 30, 2023 to June 30, 2024','six-month comparison',False),
    ('six months ended June 30, 2023 to six months ended June 29, 2024','six-month comparison',False),
    ('six months ended June 30, 2023 to six months ended June 30, 2024','six-month increase',False),
])
def test_reporting_comparison_duration_needs_both_complete_literal_scopes(scope,phrase,accepted):
    from adaptive_document_agent.agent.source_context_periods import mask_reporting_period_references

    proof=('Training costs changed from RMB 2 million in the six months ended June 30, 2023 '
           'to RMB 3 million in the six months ended June 30, 2024 due to contract timing.')
    description=f'describes contract timing as the reason for the expenditure change in this {phrase}'
    masked=mask_reporting_period_references(description,proof,scope)
    assert (phrase not in masked) is accepted


@pytest.mark.parametrize('scope,proof,description,accepted', [
    ('six months ended June 30, 2024',
     'The source discussed changes during the six months ended June 30, 2023 and six months ended June 30, 2024.',
     'describes pressure in the latest six-month period',True),
    ('six months ended June 30, 2024',
     'The source discussed changes during the six months ended June 30, 2024.',
     'describes pressure in the latest six-month period',True),
    ('2024-06-30',
     'The source discussed changes during the six months ended June 30, 2024.',
     'describes pressure in the latest six-month period',False),
    ('six months ended June 30, 2023 and six months ended June 30, 2024',
     'The source discussed changes during the six months ended June 30, 2023 and six months ended June 30, 2024.',
     'describes pressure in the latest six-month period',False),
    ('six months ended June 30, 2023',
     'The source discussed changes during the six months ended June 30, 2023 and six months ended June 30, 2024.',
     'describes pressure in the latest six-month period',False),
    ('six months ended June 30, 2024',
     'The source discussed changes during the six months ended June 30, 2024.',
     'describes pressure in the latest nine-month period',False),
])
def test_latest_months_period_requires_one_exact_scope_window_and_latest_matching_proof(
        scope,proof,description,accepted):
    from adaptive_document_agent.agent.source_context_periods import mask_reporting_period_references
    masked=mask_reporting_period_references(description,proof,scope)
    assert ('latest' not in masked) is accepted


def test_held_at_month_day_without_year_remains_unbound():
    from adaptive_document_agent.agent.source_context_periods import mask_reporting_period_references
    proof='The source discussed the six months ended June 30, 2024.'
    description='describes a balance held at June 30'
    assert any(char.isdigit() for char in mask_source_periods(description,proof))
    assert mask_reporting_period_references(description,proof,'six months ended June 30, 2024')==description


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


@pytest.mark.parametrize('scope,accepted',[
    ('2017–2018; from 2019 onwards',True),
    ('2016–2018; from 2019 onwards',False),
    ('2017–2018; from 2020 onwards',False),
])
def test_source_owned_annual_range_and_forward_scope(scope,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='Research activity slowed between 2017 and 2018; the source expects a recovery from 2019 onwards.'
    item=QualifiedSourceCopy(scope=scope,description='describes slower activity followed by an expected recovery',
                             quote=BriefQuote(page=1,text=proof))
    _,parts=reported_source_components('The source reports levels. '+qualified_source_statement(item),
                                     [item.quote],declared=[item])
    assert bool(parts)==accepted


@pytest.mark.parametrize('description,accepted',[
    ('describes the 2022 program expansion and the 2023 increase as demand-related',True),
    ('describes the 2021 program expansion as demand-related',False),
    ('reports the 2022 units as delivered',False),
])
def test_year_modifies_a_source_owned_event_without_licensing_counted_units(description,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='The program expanded as of December 31, 2022 and increased as of December 31, 2023.'
    item=QualifiedSourceCopy(scope='the program discussion',description=description,quote=BriefQuote(page=1,text=proof))
    _,parts=reported_source_components('The source reports levels. '+qualified_source_statement(item),
                                     [item.quote],declared=[item])
    assert bool(parts)==accepted


@pytest.mark.parametrize('description,proof,accepted',[
    ('describes the 2023 lengthening of inventory turnover as related to product expansion',
     'Inventory turnover days increased in 2023 as product lines expanded.',True),
    ('describes the 2022 lengthening of inventory turnover as related to product expansion',
     'Inventory turnover days increased in 2023 as product lines expanded.',False),
    ('describes the 2023 lengthening of inventory turnover by 395 days',
     'Inventory turnover days increased in 2023 as product lines expanded.',False),
    ('describes the 2023 shortening of inventory turnover as related to product expansion',
     'Inventory turnover days shortened in 2023 as product lines contracted.',True),
])
def test_source_owned_nominal_trend_year_is_not_a_measure(description,proof,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    item=QualifiedSourceCopy(scope='the inventory discussion',description=description,
                             quote=BriefQuote(page=1,text=proof))
    _,parts=reported_source_components('The source reports inventory levels. '+qualified_source_statement(item),
                                     [item.quote],declared=[item])
    assert bool(parts)==accepted


@pytest.mark.parametrize('scope,accepted',[
    ('the next 12 months from publication',True),
    ('the next twelve months from publication',True),
    ('the next 18 months from publication',False),
    ('the next 12 years from publication',False),
])
def test_future_duration_scope_requires_same_source_condition(scope,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='Management expects adequate resources for the next 12 months from publication.'
    item=QualifiedSourceCopy(scope=scope,description='describes management’s assessment of resource adequacy',
                             quote=BriefQuote(page=1,text=proof))
    _,parts=reported_source_components('The source reports levels. '+qualified_source_statement(item),
                                     [item.quote],declared=[item])
    assert bool(parts)==accepted


def test_coordinated_calendar_scope_keeps_all_source_dates():
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates,bound_period_dates
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    scope='December 31, 2017, 2018 and 2019 and June 30, 2020'
    proof='Resources were assessed as of '+scope+'.'
    dates={'2017-12-31','2018-12-31','2019-12-31','2020-06-30'}
    assert literal_calendar_dates(proof)==dates
    item=QualifiedSourceCopy(scope=scope,description='describes the resource assessment at those reporting dates',
                             quote=BriefQuote(page=1,text=proof))
    statement=bound_period_dates(qualified_source_statement(item),dates)
    _,parts=reported_source_components('The source reports levels. '+statement,
                                     [item.quote],periods=dates,declared=[item])
    assert parts==[statement]
    assert bound_period_dates(scope,dates-{'2018-12-31'},mask=True) is None
    assert '2016-12-31' not in literal_calendar_dates('Resources for 2016 units were assessed on June 30, 2020.')


@pytest.mark.parametrize('text',[
    'On December 31, 2017, 2018 units were delivered.',
    'On December 31, 2017, 2018 and 2019 participants joined.',
])
def test_calendar_list_cannot_invent_dates_from_counted_nouns(text):
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates
    assert literal_calendar_dates(text)=={'2017-12-31'}


def test_coordinated_calendar_dates_preserve_order_and_reject_nonleap_year():
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates,bound_period_dates
    text='December 31, 2020, 2018 and 2019'
    assert bound_period_dates(text,literal_calendar_dates(text))=='2020-12-31, 2018-12-31, 2019-12-31'
    assert bound_period_dates('February 29, 2020 and 2021',{'2020-02-29'},mask=True) is None


@pytest.mark.parametrize('scope',['31 Dec 2022','December 31, 2022','2022-12-31'])
def test_full_bound_date_is_not_partially_masked_as_month_and_year(scope):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    from adaptive_document_agent.services.calendar_claims import bound_period_dates
    proof='The source describes the resource assessment and management’s judgment.'
    item=QualifiedSourceCopy(scope=scope,description='describes the resource assessment and management’s judgment',
                             quote=BriefQuote(page=1,text=proof))
    periods=['31 Dec 2022']
    statement=bound_period_dates(qualified_source_statement(item),periods)
    _,parts=reported_source_components('The source reports levels. '+statement,
        [item.quote],periods=periods,declared=[item])
    assert parts==[statement]


@pytest.mark.parametrize('boundary,accepted',[
    ('over-two-year',True),('over-three-year',False),('under-two-year',False),
])
def test_hyphenated_source_boundary_preserves_exact_operator_and_duration(boundary,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='Management considers cases with an age of more than 2 years generally aligned with expectations.'
    item=QualifiedSourceCopy(scope='the source discussion',
        description='describes the '+boundary+' category as generally aligned with management expectations',
        quote=BriefQuote(page=1,text=proof))
    _,parts=reported_source_components('The source reports levels. '+qualified_source_statement(item),
        [item.quote],declared=[item])
    assert bool(parts)==accepted


@pytest.mark.parametrize('year,accepted',[('2018',True),('2016',False)])
def test_semicolon_scope_list_requires_each_source_owned_year(year,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='Activity was stable in 2017 and 2018, then recovered in 2019 and for the six months ended June 30, 2020.'
    item=QualifiedSourceCopy(scope=f'2017; {year}; 2019; six months ended June 30, 2020',
        description='describes an initially stable phase followed by a recovery',quote=BriefQuote(page=1,text=proof))
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates,bound_period_dates
    dates=literal_calendar_dates(proof)
    statement=bound_period_dates(qualified_source_statement(item),dates)
    _,parts=reported_source_components('The source reports levels. '+statement,[item.quote],periods=dates,declared=[item])
    assert bool(parts)==accepted


@pytest.mark.parametrize('count,unit,ended,reference',[
    ('nine','months','September 30, 2020','nine-month'),
    ('three','weeks','September 27, 2019','three-week'),
])
def test_worded_reporting_duration_keeps_exact_source_endpoint_and_proof(count,unit,ended,reference):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    from adaptive_document_agent.services.calendar_claims import literal_calendar_dates,bound_period_dates
    proof=f'The programme experienced delivery delays for the {count} {unit} ended {ended}.'
    dates=literal_calendar_dates(proof)
    item=QualifiedSourceCopy(scope=next(iter(dates)),description=
        f'describes delivery delays during the {reference} period',quote=BriefQuote(page=1,text=proof))
    statement=bound_period_dates(qualified_source_statement(item),dates)
    _,parts=reported_source_components('The source reports levels. '+statement,[item.quote],periods=dates,declared=[item])
    assert parts==[statement] and item.quote.text==proof


@pytest.mark.parametrize('text,scope',[
    ('Delays occurred during the six-month period.','2020-09-30'),
    ('Delays occurred during the nine-week period.','2020-09-30'),
    ('Delays occurred during the nine-month period.','2020-06-30'),
    ('Delays occurred during the nine-month period.','9M2020'),
    ('Delays lasted nine months.','2020-09-30'),
    ('Delays lasted for nine months.','2020-09-30'),
    ('Delays occurred during the 9-month period.','2020-09-30'),
])
def test_reporting_reference_cannot_authorize_other_durations_measurements_or_inferred_dates(text,scope):
    from adaptive_document_agent.agent.source_context_periods import mask_reporting_period_references
    proof='The programme had delivery delays for the nine months ended September 30, 2020.'
    assert mask_reporting_period_references(text,proof,scope)==text


@pytest.mark.parametrize('description,accepted',[
    ('describes the 2020 balance and the 2020 increases as linked to procurement',True),
    ('describes the 2020 reductions as linked to procurement',True),
    ('attributes the 2020 prolongation to procurement',True),
    ('attributes the 2019 prolongation to procurement',False),
    ('attributes the 2020 units prolongation to procurement',False),
    ('attributes the 2020 interim increase to procurement',False),
    ('attributes the 2020 full-year increase to procurement',False),
    ('describes the 2019 balance as linked to procurement',False),
    ('describes the 2020 balances delivered to clients',False),
    ('describes the 2020 units delivered to clients',False),
    ('describes the 2020 units growth as linked to procurement',False),
    ('describes the 2020 balances reduction as linked to procurement',False),
])
def test_year_modifier_of_a_singular_reported_level_or_event_is_source_owned(description,accepted):
    from adaptive_document_agent.agent.reported_source_context import reported_source_components,qualified_source_statement
    proof='The programme balance as of September 30, 2020 reflected procurement requirements.'
    item=QualifiedSourceCopy(scope='the programme discussion',description=description,quote=BriefQuote(page=1,text=proof))
    statement=qualified_source_statement(item)
    _,parts=reported_source_components('Reported levels. '+statement,[item.quote],declared=[item])
    assert bool(parts)==accepted
