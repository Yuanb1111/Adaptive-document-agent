"""Concurrent copy repair cannot publish a partial batch or change ownership."""
from threading import Barrier, Lock

import pytest

from adaptive_document_agent.agent.retained_page_revision_parallel import (
    OwnedPageRevisionErrors, complete_owned_copy_revisions, revise_owned_pages,
)
from adaptive_document_agent.agent.retained_page_sources import AuthoredPageErrors, RejectedPageAttempt, RetainedPage


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


def test_owned_copy_repair_uses_remaining_round_only_for_the_unresolved_page():
    calls = []
    issues = {'good': ['Fix attribution'], 'bad': ['Fix dates']}

    earlier = RejectedPageAttempt(page=RetainedPage(title='Bad page',message='Unapproved copy.'),
                                  errors=['Still missing an exact period'])

    def revise(pending, attempts):
        calls.append(pending)
        if len(calls) == 1:
            assert attempts == {}
            raise OwnedPageRevisionErrors({'bad': ['Still missing an exact period']},
                {'good': 'Locally validated draft'}, rejected_attempts={'bad': [earlier]})
        assert attempts == {'bad': [earlier]}
        return {'bad': 'Corrected draft'}

    drafts, remaining = complete_owned_copy_revisions(issues, 3, revise)

    assert calls == [issues, {'bad': ['Fix dates', 'Still missing an exact period']}]
    assert drafts == {'good': 'Locally validated draft', 'bad': 'Corrected draft'}
    assert remaining == 1


def test_owned_copy_repair_cannot_return_unapproved_siblings_without_a_complete_batch():
    calls = []

    def revise(pending, attempts):
        calls.append(set(pending))
        if len(calls) == 1:
            raise OwnedPageRevisionErrors({'bad': ['Unbound amount']}, {'good': 'Candidate'})
        raise AuthoredPageErrors({'bad': ['The amount is still unbound']})

    with pytest.raises(AuthoredPageErrors, match='still unbound'):
        complete_owned_copy_revisions({'good': [], 'bad': []}, 2, revise)
    assert calls == [{'good', 'bad'}, {'bad'}]


@pytest.mark.parametrize('workers',[1,4,8])
def test_fast_dispatch_preserves_per_page_bounds_and_flags(monkeypatch,workers):
    from types import SimpleNamespace
    from adaptive_document_agent.agent import retained_page_revision as module
    calls=[]
    feedback={iid:[RejectedPageAttempt(page=RetainedPage(title='Prior copy',message=f'Candidate for {iid}.'),
                   errors=[f'Unbound claim on {iid}'])] for iid in ('a','b')}
    def batch(gateway,result,packet,aliases,draft,issues,**kwargs):
        assert kwargs==dict(earlier_issues={'a':['Prior question']},preserve_numeric_inputs=True,
                            rejected_attempts={iid:feedback[iid] for iid in issues})
        calls.append(set(issues))
        return {iid:'Unapproved' for iid in issues}
    monkeypatch.setattr(module,'_revise_page_batch',batch)
    result=module.revise_retained_pages(SimpleNamespace(discovery_workers=workers),None,{}, {}, {},
        {'a':['Current question'],'b':['Other question']},earlier_issues={'a':['Prior question']},
        preserve_numeric_inputs=True,rejected_attempts=feedback)
    assert result=={'a':'Unapproved','b':'Unapproved'}
    assert calls==[{'a'},{'b'}] if workers==8 else calls==[{'a','b'}]
