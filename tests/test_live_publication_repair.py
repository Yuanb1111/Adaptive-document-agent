"""A single invocation may fix rejected copy, but must earn a new source verdict."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_analysis_review import review_retained_analysis, review_complete
from tests.test_retained_analysis_v216 import gateway
from tests.test_retained_source_citations import fixture


def ready():
    result,_,selection=fixture()
    retained.select_retained_analysis(gateway([selection.model_dump(),
        dict(accepted=True,reason='Synthetic source selection.')]),result)
    result.presentation_plan=retained.compile_retained_analysis(result)
    return result,selection.ordered_insight_ids[0]


def verdict(result,accepted=True,omissions=True):
    return dict(verdicts=[dict(slide_id=s.id,accepted=accepted,reason='Clarify source attribution.')
        for s in result.presentation_plan.slides if s.slide_type=='analysis'],
        omissions_accepted=omissions,omission_reason='Synthetic complete review.')


def measured(monkeypatch):
    from adaptive_document_agent.agent import report_audit_scope,presentation_budget_refinement
    from adaptive_document_agent.services import slide_budgets
    calls=[]
    monkeypatch.setattr(report_audit_scope,'refresh_report_audit_scope',lambda *a,**k:calls.append('audit'))
    monkeypatch.setattr(report_audit_scope,'require_report_audit_scope',lambda *a:None)
    monkeypatch.setattr(presentation_budget_refinement,'measure',lambda r:(object(),{}))
    monkeypatch.setattr(slide_budgets,'require_exported_budgets',lambda *a:calls.append('measure'))
    return calls


def test_live_rejection_is_corrected_without_loading_checkpoint_or_restarting_analysis(monkeypatch):
    calls=measured(monkeypatch)
    result,iid=ready();before=deepcopy(result)
    text=retained.selected_record(result)['selection']['decisions'][0]['page']['message']
    llm=gateway([verdict(result,False),dict(edits={iid:dict(message=[dict(before=text,
        after='The source reports revenue with its period labels.')])}),verdict(result)])
    review_retained_analysis(llm,result,repair_copy=True)
    assert review_complete(result) and result.failed_stage is None
    assert calls==['audit','measure']
    assert [u['operation'] for u in llm.usage]==['RetainedAnalysisReview','RetainedPageRevisions','RetainedAnalysisReview']
    for field in ('document','observations','analysis_results','insights','charts'):
        assert getattr(result,field)==getattr(before,field)


def test_live_repair_is_bounded_to_two_edits_and_fails_closed(monkeypatch):
    measured(monkeypatch); result,iid=ready()
    responses=[verdict(result,False)]
    for _ in range(2):
        responses += [dict(edits={iid:{}}),verdict(result,False)]
    llm=gateway(responses)
    with pytest.raises(ValueError,match='evidence review rejected'):
        review_retained_analysis(llm,result,repair_copy=True)
    assert sum(u['operation']=='RetainedPageRevisions' for u in llm.usage)==2
    assert not review_complete(result)


def test_copy_correction_cannot_settle_a_missing_finding(monkeypatch):
    measured(monkeypatch);result,_=ready();llm=gateway([verdict(result,False,False)])
    with pytest.raises(ValueError,match='Omitted findings'):
        review_retained_analysis(llm,result,repair_copy=True)
    assert len(llm.usage)==1 and not review_complete(result)
