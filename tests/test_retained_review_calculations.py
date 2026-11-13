"""Independent reviewers see exact deterministic calculations without borrowing other owners."""
from copy import deepcopy

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_selection_coverage import _coverage_payload
from adaptive_document_agent.agent.retained_copy_review import copy_review_payload
from adaptive_document_agent.agent.retained_analysis_review import review_context
from adaptive_document_agent.services.presentation_evidence import calculation_catalog
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway
from tests.test_retained_copy_review import packet


def test_selection_reviewer_receives_the_same_python_catalog_for_bound_rows():
    result,_,selection=fixture()
    before=deepcopy(result.observations)
    context=retained.selection_context(result,source_authoring=True)
    payload,cited,_=_coverage_payload(context,selection,result)
    ids=set().union(*cited.values())
    expected=[c for c in calculation_catalog(result.observations).values() if set(c['observation_ids'])<=ids]
    assert expected and payload['bound_calculations']==expected
    assert result.observations==before


def test_owned_copy_catalog_cannot_include_an_unrelated_calculation():
    original=packet()
    original['bound_calculations']=[dict(id='owned',observation_ids=['primary','companion']),
        dict(id='foreign',observation_ids=['unrelated']),
        dict(id='mixed',observation_ids=['primary','unrelated'])]
    assert copy_review_payload(original)['bound_calculations']==original['bound_calculations'][:1]


def test_final_reviewer_receives_only_calculations_referenced_by_actual_analysis_slides():
    result,_,selection=fixture()
    retained.select_retained_analysis(gateway([selection.model_dump(),dict(
        accepted=True,reason='Synthetic complete source selection.')]),result)
    result.presentation_plan=retained.compile_retained_analysis(result)
    slide=next(s for s in result.presentation_plan.slides if s.slide_type=='analysis')
    catalog=calculation_catalog(result.observations)
    slide.calculation_ids=[next(iter(catalog))]
    context=review_context(result)
    assert context['bound_calculations']==[catalog[slide.calculation_ids[0]]]
