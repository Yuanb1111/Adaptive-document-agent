"""Concurrent copy repair cannot publish a partial batch or change ownership."""
from threading import Barrier, Lock

import pytest

from adaptive_document_agent.agent.retained_page_revision_parallel import revise_owned_pages
from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors


def test_independent_page_corrections_overlap_and_return_in_original_order():
    barrier=Barrier(4)
    issues={str(i):[f'Issue {i}'] for i in range(4)}
    def revise(owned):
        barrier.wait(timeout=10)
        iid,=owned
        assert owned=={iid:issues[iid]}
        return {iid:f'Unapproved replacement {iid}'}
    assert list(revise_owned_pages(issues,revise))==list(issues)


@pytest.mark.parametrize('failure',['source','foreign','fatal'])
def test_one_failure_drains_every_worker_and_returns_no_partial_replacements(failure):
    barrier=Barrier(3)
    finished=[]
    lock=Lock()
    def revise(owned):
        iid,=owned
        try:
            barrier.wait(timeout=10)
            if iid=='bad':
                if failure=='source': raise AuthoredPageErrors({iid:['Unbound source claim']})
                if failure=='fatal': raise RuntimeError('Unavailable reviewer')
                return {'sibling':'Wrong ownership'}
            return {iid:'Unapproved replacement'}
        finally:
            with lock: finished.append(iid)
    expected=RuntimeError if failure=='fatal' else ValueError
    with pytest.raises(expected):
        revise_owned_pages({'good':[], 'bad':[], 'other':[]},revise)
    assert set(finished)=={'good','bad','other'}


@pytest.mark.parametrize('workers',[1,4,8])
def test_fast_dispatch_preserves_per_page_bounds_and_flags(monkeypatch,workers):
    from types import SimpleNamespace
    from adaptive_document_agent.agent import retained_page_revision as module
    calls=[]
    def batch(gateway,result,packet,aliases,draft,issues,**kwargs):
        assert kwargs==dict(earlier_issues={'a':['Prior question']},preserve_numeric_inputs=True)
        calls.append(set(issues))
        return {iid:'Unapproved' for iid in issues}
    monkeypatch.setattr(module,'_revise_page_batch',batch)
    result=module.revise_retained_pages(SimpleNamespace(discovery_workers=workers),None,{}, {}, {},
        {'a':['Current question'],'b':['Other question']},earlier_issues={'a':['Prior question']},
        preserve_numeric_inputs=True)
    assert result=={'a':'Unapproved','b':'Unapproved'}
    assert calls==[{'a'},{'b'}] if workers==8 else calls==[{'a','b'}]
