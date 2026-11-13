"""A negative calculated rate keeps its sign across whole-plan validation."""
import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.services.presentation_evidence import calculation_catalog
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway


def test_negative_calculated_cagr_compiles_and_cannot_become_positive():
    result,_,selection=fixture()
    for item,period,raw in zip(result.observations,['FY2021','FY2022','FY2023'],['65.9','61.4','56.6']):
        item.metric_original=item.metric_canonical='ASP'
        item.period=period
        item.raw_value=raw
        item.value=float(raw)*1000
        item.currency='RMB'
        item.unit='currency'
        item.raw_unit='RMB in thousands/unit'
        item.unit_family='currency'
        item.unit_scale=1000
    result.document.pages[0].text='ASP (RMB in thousands/unit): FY2021 65.9; FY2022 61.4; FY2023 56.6.'
    page=selection.decisions[0].page
    page.title='ASP'
    page.message=('ASP (RMB in thousands/unit): 65.9 in FY2021, 61.4 in FY2022 and 56.6 in FY2023. '
        'The calculated CAGR was -7.3% from FY2021 to FY2023.')
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic source selection.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    catalog=calculation_catalog(result.observations)
    assert any(catalog[cid]['kind']=='cagr' and catalog[cid]['display']=='-7.3%'
               for cid in slide.calculation_ids)
    assert PresentationPlanValidator().validate(plan,result) is plan
    slide.message=slide.message.replace('-7.3%','7.3%')
    with pytest.raises(ValueError,match='unsupported numeric claims|contradict'):
        PresentationPlanValidator().validate(plan,result)
