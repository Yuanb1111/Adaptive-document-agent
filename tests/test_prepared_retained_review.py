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


def fail_source_integration(result):
    result.pipeline_state = 'partial'
    result.retry_from = 'reporting'
    result.failed_stage = 'source_integration'
    result.failure_details = dict(component='SourceIntegration', message='Supplementary source check unresolved.')


@pytest.mark.parametrize('accepted', [True, False])
def test_completed_parallel_verdict_survives_source_failure_and_uses_existing_gate(monkeypatch, accepted):
    from adaptive_document_agent.agent.retained_analysis import selected_record
    measured(monkeypatch)
    result, iid = ready()
    fresh = result.model_copy(deep=True)
    original = gateway([verdict(result, accepted)])
    parallel = SimpleNamespace(discovery_workers=2, generate_structured=original.generate_structured)
    with prepare_retained_review(parallel, result) as job:
        assert job is not None
        if accepted:
            job.future.result(timeout=10)
        else:
            with pytest.raises(ValueError, match='rejected'):
                job.future.result(timeout=10)
        fail_source_integration(result)
    assert result.pipeline_state == 'partial' and result.failure_details['component'] == 'SourceIntegration'
    assert len([w for w in result.validation_warnings if w.code == review.REVIEW_CODE]) == 1
    assert review.review_complete(result) is accepted

    # A second failed supplement must preserve the completed sibling verdict too.
    checkpoint = fresh.model_copy(deep=True)
    with prepare_retained_review(gateway([]), checkpoint, previous=result):
        fail_source_integration(checkpoint)
    assert checkpoint.validation_warnings[-1] == result.validation_warnings[-1]

    text = selected_record(fresh)['selection']['decisions'][0]['page']['message']
    edits = dict(edits={iid: dict(message=[dict(before=text, after='The source reports revenue with its period labels.')])})
    llm = gateway([] if accepted else [edits, verdict(fresh)])
    with prepare_retained_review(llm, fresh, previous=checkpoint) as resumed:
        assert resumed is not None
        failure = resumed.attach(fresh)
        assert isinstance(failure, ValueError) is (not accepted)
        review.review_retained_analysis(llm, fresh, repair_copy=True, initial_failure=failure)
    assert review.review_complete(fresh)
    assert [u['operation'] for u in llm.usage] == ([] if accepted else ['RetainedPageRevisions', 'RetainedAnalysisReview'])


@pytest.mark.parametrize('invalid', ['source', 'missing_slide', 'duplicate_slide', 'stage', 'changed_after_restore'])
def test_saved_independent_verdict_cannot_override_current_source_or_invalid_scope(invalid):
    original, _ = ready()
    fresh = original.model_copy(deep=True)
    review.review_retained_analysis(gateway([verdict(original)]), original)
    fail_source_integration(original)
    issue = original.validation_warnings[-1]
    if invalid == 'source':
        fresh.document.pages[0].text += ' Changed evidence.'
    elif invalid in {'missing_slide', 'duplicate_slide'}:
        audit = json.loads(issue.message)
        verdicts = audit['review']['verdicts']
        audit['review']['verdicts'] = verdicts[:-1] if invalid == 'missing_slide' else verdicts + verdicts[:1]
        issue.message = json.dumps(audit)
    elif invalid == 'stage':
        original.failed_stage = 'executive_brief'
    with prepare_retained_review(gateway([]), fresh, previous=original) as restored:
        if invalid == 'changed_after_restore':
            fresh.document.pages[0].text += ' Changed after the supplement completed.'
            assert restored is not None and restored.attach(fresh) is None
        else:
            assert restored is None
    assert not review.review_complete(fresh)
    assert not any(w.code == review.REVIEW_CODE for w in fresh.validation_warnings)


def test_background_failure_without_a_verdict_leaves_only_source_failure(monkeypatch):
    result, _ = ready()
    def failed(*args):
        raise RuntimeError('Unusable independent response')
    monkeypatch.setattr(review, 'review_retained_analysis', failed)
    with prepare_retained_review(SimpleNamespace(discovery_workers=2), result) as job:
        with pytest.raises(RuntimeError):
            job.future.result(timeout=10)
        fail_source_integration(result)
    assert result.failed_stage == 'source_integration'
    assert not any(w.code == review.REVIEW_CODE for w in result.validation_warnings)


def test_unreadable_final_review_context_does_not_replace_source_failure():
    result, _ = ready()
    original = gateway([verdict(result)])
    parallel = SimpleNamespace(discovery_workers=2, generate_structured=original.generate_structured)
    with prepare_retained_review(parallel, result) as job:
        job.future.result(timeout=10)
        result.presentation_plan = None
        fail_source_integration(result)
    assert result.failure_details['component'] == 'SourceIntegration'
    assert not any(w.code == review.REVIEW_CODE for w in result.validation_warnings)
