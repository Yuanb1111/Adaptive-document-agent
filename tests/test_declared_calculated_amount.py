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


def test_percentage_is_not_interpreted_as_an_untyped_monetary_delta():
    text='Balance had a calculated increase of 200.0% from 2021-12-31 to 2024-10-31.'
    assert not list(checked_money_amounts(text,rows(),calculation_catalog(rows()).values()))


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
