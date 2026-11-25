"""A single invocation may fix rejected copy, but must earn a new source verdict."""
import json
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
    prompt=' '.join(message['content'] for message in llm.client.calls[0])
    assert 'omissions_accepted concerns ONLY whether excluded FINDINGS' in prompt
    assert 'reject that slide' in prompt
    assert 'must be corrected and receive a fresh independent review' in prompt
    recheck = llm.client.calls[-1][-1]['content'].split('<UNTRUSTED_DOCUMENT_CONTENT>', 1)[1]
    packet = json.loads(recheck.split('</UNTRUSTED_DOCUMENT_CONTENT>', 1)[0])
    slides = [s for s in result.presentation_plan.slides if s.slide_type == 'analysis']
    assert packet['slides'] == [s.model_dump(mode='json') for s in slides]
    assert packet['previous_review_questions'] == [
        dict(slide_id=s.id, question='Clarify source attribution.') for s in slides]
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


def test_material_copy_over_budget_uses_model_selection_then_fresh_source_verdict(monkeypatch):
    calls=measured(monkeypatch)
    from adaptive_document_agent.agent import retained_budget_refinement
    from adaptive_document_agent.services import slide_budgets
    checks=[]
    def require(*args):
        checks.append('measure')
        if len(checks)==1:
            raise ValueError('Analysis has an extra physical page')
    monkeypatch.setattr(slide_budgets,'require_exported_budgets',require)
    monkeypatch.setattr(retained_budget_refinement,'refine_retained_budget',
        lambda *a,**k:calls.append('model-owned-selection'))
    result,iid=ready()
    llm=gateway([verdict(result,False),dict(edits={iid:{}}),verdict(result)])
    review_retained_analysis(llm,result,repair_copy=True)
    assert calls==['audit','model-owned-selection'] and checks==['measure','measure']
    assert review_complete(result)
    assert [row['operation'] for row in llm.usage]==[
        'RetainedAnalysisReview','RetainedPageRevisions','RetainedAnalysisReview']


def test_rejected_omission_routes_through_bounded_repair_and_earns_fresh_verdict(monkeypatch):
    calls=measured(monkeypatch)
    result,_=ready()
    from adaptive_document_agent.agent import retained_omission_repair
    repairs=[]
    def repair(llm,current,review):
        repairs.append((llm,current,review.omission_reason))
        return True
    monkeypatch.setattr(retained_omission_repair,'repair_retained_omission',repair)
    llm=gateway([verdict(result,True,False),verdict(result,True,True)])

    review_retained_analysis(llm,result,repair_copy=True)

    assert repairs==[(llm,result,'Synthetic complete review.')]
    assert review_complete(result) and result.failed_stage is None
    assert calls==['audit','measure']
    assert [u['operation'] for u in llm.usage]==['RetainedAnalysisReview','RetainedAnalysisReview']
    audit=[w for w in result.validation_warnings if w.code=='presentation_retained_analysis_review']
    assert len(audit)==2
    assert json.loads(audit[0].message)['review']['omissions_accepted'] is False
    assert json.loads(audit[1].message)['review']['omissions_accepted'] is True


def test_rejected_omission_repair_without_eligible_candidate_fails_closed(monkeypatch):
    measured(monkeypatch)
    result,_=ready()
    from adaptive_document_agent.agent import retained_omission_repair
    repairs=[]
    monkeypatch.setattr(retained_omission_repair,'repair_retained_omission',
                        lambda *args: repairs.append(args) or False)
    llm=gateway([verdict(result,True,False)])

    with pytest.raises(ValueError,match='evidence review rejected'):
        review_retained_analysis(llm,result,repair_copy=True)

    assert len(repairs)==1
    assert [u['operation'] for u in llm.usage]==['RetainedAnalysisReview']
    assert not review_complete(result)
