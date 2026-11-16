"""Page-bound source IDs define calculations; other tables remain distinct evidence."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.services.presentation_evidence import (
    calculation_catalog,scoped_calculation_catalog,plan_calculation_catalog)
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway


def conflicting_tables():
    result,_,selection=fixture()
    for row,raw in zip(result.observations,['1,100','1,600','2,500']):
        row.raw_value=raw;row.value=float(raw.replace(',',''))*1000
        row.raw_unit='RMB in thousands';row.unit='currency';row.unit_family='currency';row.unit_scale=1000
    primary=list(result.observations)
    result.observations.extend(row.model_copy(deep=True,update={
        'id':row.id+'-other-table','table_id':'other-table','raw_value':'9,900','value':9900000})
        for row in primary)
    return result,selection,primary


def test_scope_recomputes_only_exact_declared_inputs_without_removing_conflicting_rows():
    result,_,primary=conflicting_tables();before=deepcopy(result.observations)
    assert not calculation_catalog(result.observations)
    local=calculation_catalog(primary)
    scoped=scoped_calculation_catalog(result.observations,[[o.id for o in primary]])
    assert scoped==local and result.observations==before
    assert not scoped_calculation_catalog(result.observations,[[o.id for o in primary]+['unknown']])
    result.observations[0].anomaly_notes.append('Source value requires review.')
    assert not scoped_calculation_catalog(result.observations,[[o.id for o in primary]])


def test_compiler_validator_and_review_catalog_share_the_same_page_bound_python_result():
    result,selection,primary=conflicting_tables()
    page=selection.decisions[0].page;page.context_evidence=[]
    page.message='Revenue rose from FY2023 to FY2025; the calculated change was RMB 1,400 thousand.'
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic exact-scope protocol.')]),result)
    plan=retained.compile_retained_analysis(result)
    slide=next(s for s in plan.slides if s.slide_type=='analysis')
    catalog=plan_calculation_catalog(result,plan)
    assert slide.calculation_ids and all(cid in catalog for cid in slide.calculation_ids)
    assert all(set(catalog[cid]['observation_ids'])<=set(slide.observation_ids) for cid in slide.calculation_ids)
    assert PresentationPlanValidator().validate(plan,result) is plan
    from adaptive_document_agent.agent.retained_analysis_review import review_complete
    assert not review_complete(result)
    slide.message=slide.message.replace('1,400','1,401')
    with pytest.raises(ValueError):PresentationPlanValidator().validate(plan,result)
