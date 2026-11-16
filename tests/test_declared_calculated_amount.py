"""A declared display unit cannot lend an arbitrary derived number to a claim."""
import pytest

from adaptive_document_agent.models import Observation
from adaptive_document_agent.services.presentation_evidence import calculation_catalog
from adaptive_document_agent.validation.presentation_numeric_evidence import checked_money_amounts
from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support


def rows():
    return [Observation(id=str(i),metric_original='Balance',period=period,raw_value=raw,
        value=value,raw_unit='USD in thousands',unit='currency',currency='USD',
        unit_scale=1000,unit_family='currency',confidence=1,validation_status='valid',
        evidence=[dict(page=1,text='Original balance table.',extraction_method='table',confidence=1)])
        for i,(period,raw,value) in enumerate([
            ('2021-12-31','1,200',1200000),('2024-10-31','3,600',3600000)])]


@pytest.mark.parametrize('declaration',['(USD in thousands)','(USD in thousands.)'])
def test_correct_explicitly_labelled_scaled_delta_uses_its_exact_python_calculation(declaration):
    observations=rows();catalog=calculation_catalog(observations)
    text=declaration+' Balance had a calculated increase of 2,400 from 2021-12-31 to 2024-10-31.'
    checked=list(checked_money_amounts(text,observations,catalog.values()))
    assert checked and all(ok for _,ok,_ in checked)
    ids=set().union(*(ids for _,_,ids in checked))
    assert len(ids)==1 and catalog[next(iter(ids))]['kind']=='absolute_change'
    assert _numeric_support(text,observations)


@pytest.mark.parametrize('text',[
    '(USD in thousands) Balance had a calculated increase of 2,399 from 2021-12-31 to 2024-10-31.',
    '(USD in millions) Balance had a calculated increase of 2,400 from 2021-12-31 to 2024-10-31.',
    '(EUR in thousands) Balance had a calculated increase of 2,400 from 2021-12-31 to 2024-10-31.',
    'Balance had a calculated increase of 2,400 from 2021-12-31 to 2024-10-31.',
    '(USD in thousands) Balance had a calculated increase of 2,400 by 2024-10-31.',
    '(USD in thousands) Balance had a calculated increase of 2,400 from 2024-10-31 to 2021-12-31.',
    '(USD in thousands) Other assets had a calculated increase of 2,400 from 2021-12-31 to 2024-10-31.',
    '(USD in thousands) Balance had a calculated decrease of 2,400 from 2021-12-31 to 2024-10-31.',
    '(USD in thousands) Balance had a calculated increase of -2,400 from 2021-12-31 to 2024-10-31.',
])
def test_wrong_value_unit_currency_interval_metric_and_sign_are_rejected(text):
    observations=rows()
    assert not _numeric_support(text,observations)


def test_calculated_value_does_not_authorize_an_unlabelled_level():
    assert not _numeric_support('(USD in thousands) Balance was 2,400.',rows())


def test_explicit_signed_change_preserves_the_python_sign():
    assert _numeric_support('(USD in thousands) Balance had a calculated signed change of 2,400 from 2021-12-31 to 2024-10-31.',rows())
    assert not _numeric_support('(USD in thousands) Balance had a calculated signed change of -2,400 from 2021-12-31 to 2024-10-31.',rows())


def test_percentage_is_not_interpreted_as_an_untyped_monetary_delta():
    text='Balance had a calculated increase of 200.0% from 2021-12-31 to 2024-10-31.'
    assert not list(checked_money_amounts(text,rows(),calculation_catalog(rows()).values()))


@pytest.mark.parametrize('prefix,accepted',[
    ('Balance rose from 2021-12-31 to 2024-10-31; the calculated change was ',True),
    ('Other assets rose from 2021-12-31 to 2024-10-31; the calculated change was ',False),
    ('Balance rose from 2021-12-31 to 2023-10-31; the calculated change was ',False),
    ('Balance rose from 2021-12-31 to 2024-10-31. The calculated change was ',False),
    ('Balance rose from 2021-12-31 to 2024-10-31 and from 2021-12-31 to 2024-10-31; the calculated change was ',False),
])
def test_same_sentence_antecedent_requires_one_explicit_metric_and_exact_interval(prefix,accepted):
    from adaptive_document_agent.validation.presentation_numeric_evidence import mask_declared_calculated_amounts
    text=prefix+'USD 2,400 thousand.'
    masked=mask_declared_calculated_amounts(text,rows(),calculation_catalog(rows()).values())
    assert ('2,400' not in masked)==accepted


def test_a_scaled_calculated_amount_compiles_with_its_id_and_cannot_be_changed():
    from tests.test_retained_source_citations import fixture
    from tests.test_retained_analysis_v216 import gateway
    from adaptive_document_agent.agent import retained_analysis as retained
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    result,_,selection=fixture()
    for row,raw in zip(result.observations,['1,125','1,700','2,485']):
        row.raw_value=raw;row.value=float(raw.replace(',',''))*1000
        row.raw_unit='RMB in thousands';row.unit='currency';row.unit_family='currency';row.unit_scale=1000
    page=selection.decisions[0].page
    page.context_evidence=[]
    page.message='(RMB in thousands) Revenue had a calculated increase of 1,360 from FY2023 to FY2025.'
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete source selection.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    assert slide.calculation_ids
    assert PresentationPlanValidator().validate(plan,result) is plan
    slide.message=slide.message.replace('1,360','1,361')
    with pytest.raises(ValueError):PresentationPlanValidator().validate(plan,result)


@pytest.mark.parametrize('currency',['USD','EUR','RMB'])
@pytest.mark.parametrize('amount',['-2,400 thousand','-2.4 million'])
def test_explicit_currency_scaled_change_is_bound_to_one_occurrence(currency,amount):
    from adaptive_document_agent.validation.presentation_numeric_evidence import mask_declared_calculated_amounts
    observations=rows()
    for row,value in zip(observations,[3600000,1200000]):
        row.currency=currency;row.value=value;row.raw_value=str(value/1000)
    catalog=calculation_catalog(observations)
    text=f'Balance had a calculated change of {currency} {amount} from 2021-12-31 to 2024-10-31.'
    masked=mask_declared_calculated_amounts(text,observations,catalog.values())
    assert amount not in masked
    # Identical digits in another unlabelled statement gain no support.
    other=f' Another reported balance was {currency} {amount}.'
    assert mask_declared_calculated_amounts(text+other,observations,catalog.values()).endswith(other)
    assert mask_declared_calculated_amounts(text,observations,())==text


@pytest.mark.parametrize('replacement',[
    'USD -2,399 thousand','USD 2,400 thousand','EUR -2,400 thousand','USD -2,400 million',
])
def test_explicit_currency_change_rejects_wrong_quantity_sign_currency_and_scale(replacement):
    from adaptive_document_agent.validation.presentation_numeric_evidence import mask_declared_calculated_amounts
    observations=rows()
    for row,value in zip(observations,[3600000,1200000]):row.value=value
    text=f'Balance had a calculated change of {replacement} from 2021-12-31 to 2024-10-31.'
    assert mask_declared_calculated_amounts(text,observations,calculation_catalog(observations).values())==text


@pytest.mark.parametrize('ending',[
    'from 2021-12-31 to 2023-10-31.',
    'from 2024-10-31 to 2021-12-31.',
    'by 2024-10-31.',
])
def test_explicit_currency_change_needs_exact_calculation_interval(ending):
    from adaptive_document_agent.validation.presentation_numeric_evidence import mask_declared_calculated_amounts
    observations=rows()
    text='Balance had a calculated increase of USD 2,400 thousand '+ending
    assert mask_declared_calculated_amounts(text,observations,calculation_catalog(observations).values())==text


@pytest.mark.parametrize('metric',['Research budget','Program funding','Operating balance'])
@pytest.mark.parametrize('amount',['-RMB 1,360 thousand','RMB -1.36 million'])
@pytest.mark.parametrize('name_in_label',[False,True])
def test_signed_currency_delta_survives_retained_compilation_for_generic_measures(metric,amount,name_in_label):
    from tests.test_retained_source_citations import fixture
    from tests.test_retained_analysis_v216 import gateway
    from adaptive_document_agent.agent import retained_analysis as retained
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
    result,_,selection=fixture()
    for row,raw in zip(result.observations,['2,485','1,700','1,125']):
        row.metric_original=metric;row.metric_canonical=None
        row.raw_value=raw;row.value=float(raw.replace(',',''))*1000
        row.raw_unit='RMB in thousands';row.unit='currency';row.unit_family='currency';row.unit_scale=1000
    insight=result.insights[0]
    insight.title=metric;insight.narrative=f'{metric} changed during the reported periods.'
    page=selection.decisions[0].page
    page.title=metric;page.context_evidence=[]
    subject=f' in {metric}' if name_in_label else ''
    page.message=f'{metric}: the calculated change{subject} was {amount} from FY2023 to FY2025.'
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete source selection.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    assert slide.calculation_ids and amount in slide.message
    assert PresentationPlanValidator().validate(plan,result) is plan
    slide.calculation_ids=[]
    with pytest.raises(ValueError):PresentationPlanValidator().validate(plan,result)


@pytest.mark.parametrize('currency',['USD','EUR','RMB'])
@pytest.mark.parametrize('scale,suffix',[(1,' units'),(1000,' thousand'),(10**6,' million')])
def test_python_change_catalog_supplies_explicit_display_scale_without_mutating_inputs(currency,scale,suffix):
    from copy import deepcopy
    observations=rows()
    for row,value in zip(observations,[3600*scale,1200*scale]):
        row.currency=currency;row.unit_scale=scale;row.value=value
        row.raw_value=str(value//scale);row.raw_unit=currency+' in '+suffix.strip()
    before=deepcopy(observations)
    calc=next(c for c in calculation_catalog(observations).values() if c['kind']=='absolute_change')
    assert calc['amount_literal']==currency+' -2,400'+suffix
    text=f'({currency} in thousands) Balance had a calculated change of '+calc['amount_literal']+' from 2021-12-31 to 2024-10-31.'
    assert _numeric_support(text,observations)
    assert observations==before


def test_base_unit_delta_under_wrong_paragraph_scale_remains_rejected_with_exact_feedback():
    observations=rows();failures=[]
    text='(USD in thousands) Balance had a calculated change of USD 2,400,000 from 2021-12-31 to 2024-10-31.'
    assert not _numeric_support(text,observations,diagnostics=failures)
    assert 'USD 2,400 thousand' in ' '.join(failures)
    assert not list(checked_money_amounts('The sample contained 12 units.',observations))


@pytest.mark.parametrize('typed',[True,False])
def test_full_metric_change_label_cannot_borrow_another_measure(typed):
    from adaptive_document_agent.validation.presentation_numeric_evidence import mask_declared_calculated_amounts
    observations=rows();catalog=calculation_catalog(observations)
    amount='USD 2,400 thousand' if typed else '2,400'
    text='(USD in thousands) The calculated increase in Other assets was '+amount+' from 2021-12-31 to 2024-10-31.'
    assert mask_declared_calculated_amounts(text,observations,catalog.values())==text
    correct=text.replace('Other assets','Balance')
    assert amount not in mask_declared_calculated_amounts(correct,observations,catalog.values())
