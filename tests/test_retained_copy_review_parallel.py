"""Owned semantic reviews overlap without granting selection/publication authority."""
import json
from threading import Barrier,Lock
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.retained_copy_review_parallel import review_owned_copy
from adaptive_document_agent.agent.retained_selection_coverage import (
    RetainedSelectionCoverage,SelectionCoverageError)


class Result:
    def __init__(self):self.validation_warnings=[]
    def model_copy(self,*,update):return SimpleNamespace(**update)


@pytest.mark.parametrize('failure',[None,'source','fatal','foreign'])
def test_complete_owned_batch_preserves_sources_drains_failures_and_never_approves_a_deck(failure):
    result=Result();barrier=Barrier(3);lock=Lock();finished=[]
    pages=[dict(page=1,text='Complete source.'),dict(page=2,text='Related qualification.')]
    context=dict(copy_review_ids=['a','b','c'],source_pages=pages)
    selection=SimpleNamespace(ordered_insight_ids=['a','b','c','frozen'])
    def review(own,current):
        iid,=own['copy_review_ids']
        assert own['source_pages'] is pages and current is not result
        try:
            barrier.wait(timeout=10)
            if iid=='b' and failure=='fatal':raise RuntimeError('Source reviewer unavailable')
            bad=iid=='b' and failure in {'source','foreign'}
            verdict=RetainedSelectionCoverage(accepted=not bad,
                page_issues=[dict(insight_id='a' if failure=='foreign' else iid,
                    reason='Material source qualification missing.')] if bad else [],reason='Source review.')
            current.validation_warnings.append(SimpleNamespace(code='retained_selection_coverage',
                message=json.dumps(dict(input_fingerprint=iid,review=verdict.model_dump()))))
            if bad:raise SelectionCoverageError('Rejected source copy.',verdict)
        finally:
            with lock:finished.append(iid)
    if failure:
        expected=SelectionCoverageError if failure=='source' else RuntimeError if failure=='fatal' else ValueError
        with pytest.raises(expected):review_owned_copy(context,selection,result,context,review)
    else:
        review_owned_copy(context,selection,result,context,review)
    assert set(finished)=={'a','b','c'}
    assert context['copy_review_ids']==['a','b','c'] and selection.ordered_insight_ids[-1]=='frozen'
    if failure in {None,'source'}:
        audit=json.loads(result.validation_warnings[-1].message)
        assert audit['copy_review_ids']==['a','b','c']
        assert len(audit['owned_reviews'])==3 and audit['final_presentation_approval'] is False
        assert audit['review']['accepted']==(failure is None)
        assert [p['insight_id'] for p in audit['review']['page_issues']]==(['b'] if failure else [])
