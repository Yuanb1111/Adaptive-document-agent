"""Independent review overlaps work but cannot approve changed source inputs."""
import json
from threading import Event
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent import retained_analysis_review as review
from adaptive_document_agent.agent.prepared_retained_review import PreparedRetainedReview, prepare_retained_review
from adaptive_document_agent.models import ValidationIssue
from tests.test_live_publication_repair import ready, verdict, measured
from tests.test_retained_analysis_v216 import gateway


@pytest.mark.parametrize('change',['none','brief','source','observation','slide'])
def test_isolated_review_attaches_only_at_identical_final_context(monkeypatch,change):
    result,_=ready();started=Event();release=Event()
    def independent(gate,snapshot):
        started.set();assert release.wait(5)
        context=review.review_context(snapshot)
        snapshot.validation_warnings.append(ValidationIssue(code=review.REVIEW_CODE,stage='presentation',
            severity='info',message=json.dumps(dict(contract=1,fingerprint=review.fingerprint(context),
                                                    review=verdict(snapshot)))))
    monkeypatch.setattr(review,'review_retained_analysis',independent)
    prepared=PreparedRetainedReview(None,result)
    try:
        assert started.wait(5)
        if change=='source':result.document.pages[0].text+=' Source changed.'
        elif change=='observation':result.observations[0].raw_value='999'
        elif change=='slide':
            next(s for s in result.presentation_plan.slides if s.slide_type=='analysis').message+=' Changed.'
        elif change=='brief':
            from adaptive_document_agent.models.executive_brief import ExecutiveBrief
            result.executive_brief=ExecutiveBrief(title='Additional audience context',items=[dict(
                label='Context',text='Additional audience context.',evidence=[dict(page=1,text='Literal source context.')])])
        release.set();assert prepared.attach(result) is None
        assert review.review_complete(result)==(change in {'none','brief'})
    finally:
        release.set();prepared.close()


def test_prepared_rejection_uses_existing_two_edit_budget_without_repeating_first_review(monkeypatch):
    measured(monkeypatch);result,iid=ready()
    from adaptive_document_agent.agent.retained_analysis import selected_record
    text=selected_record(result)['selection']['decisions'][0]['page']['message']
    llm=gateway([verdict(result,False),dict(edits={iid:dict(message=[dict(before=text,
        after='The source reports revenue with its period labels.')])}),verdict(result)])
    prepared=PreparedRetainedReview(llm,result)
    try:
        failure=prepared.attach(result)
        assert isinstance(failure,ValueError)
        review.review_retained_analysis(llm,result,repair_copy=True,initial_failure=failure)
        assert review.review_complete(result)
        assert [u['operation'] for u in llm.usage]==['RetainedAnalysisReview',
            'RetainedPageRevisions','RetainedAnalysisReview']
    finally:prepared.close()


@pytest.mark.parametrize('workers,physical',[(1,False),(8,True)])
def test_serial_or_audience_dependent_review_stays_serial(monkeypatch,workers,physical):
    from adaptive_document_agent.agent import retained_analysis
    monkeypatch.setattr(retained_analysis,'selected_record',lambda r:dict(physical_budget={'bound':True})
                        if physical else dict(source_authoring=True))
    with prepare_retained_review(SimpleNamespace(discovery_workers=workers),object()) as prepared:
        assert prepared is None
