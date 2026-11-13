"""Topic omission review and owned copy review have separate authority."""
import json
from threading import Barrier
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent import retained_selection_coverage as module
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.utils.record_encoding import decode_records
from tests.test_retained_source_citations import fixture
from tests.test_retained_analysis_v216 import gateway


def test_priority_review_preserves_raw_sources_and_does_not_review_page_copy():
    result,context,selection=fixture()
    llm=gateway([dict(accepted=True,prioritized_insight_ids=[],reason='Selection is defensible.')])
    module._review_selection_coverage(llm,context,selection,result,priority_only=True)
    assert llm.usage[0]['operation']=='RetainedPriorityCoverage'
    packet=decode_records(json.loads(llm.client.calls[0][-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
    assert packet['source_pages']==context['source_pages']
    assert all('page' not in d for d in packet['proposed_selection']['decisions'])
    audit=json.loads(result.validation_warnings[-1].message)
    assert audit['priority_only'] and not audit['final_presentation_approval']
    assert 'source_context' not in packet['proposed_selection']['decisions'][0]


def test_missing_ids_compile_only_from_the_independent_models_complete_priority_choice():
    result,context,selection=fixture()
    extra={**context['findings'][0],'insight':{**context['findings'][0]['insight'],'id':'indispensable'}}
    context['findings'].append(extra)
    llm=gateway([dict(accepted=False,prioritized_insight_ids=['indispensable'],reason='Material contrary finding.')])
    with pytest.raises(module.SelectionCoverageError) as caught:
        module._review_selection_coverage(llm,context,selection,result,priority_only=True)
    assert caught.value.priority_ids==['indispensable']
    review=json.loads(result.validation_warnings[-1].message)['review']
    assert review['missing_insight_ids']==['indispensable'] and review['page_issues']==[]


@pytest.mark.parametrize('reject_priority',[False,True])
def test_fast_initial_review_requires_priority_verdict_then_every_owned_source_verdict(monkeypatch,reject_priority):
    from adaptive_document_agent.agent import retained_copy_review
    from tests.test_retained_copy_review_parallel import Result
    result=Result();selection=SimpleNamespace(ordered_insight_ids=['a','b'])
    pages=[dict(page=1,text='Complete source'),dict(page=2,text='Continued qualification')]
    context=dict(source_pages=pages,copy_review_ids=[])
    calls=[];barrier=Barrier(2)
    def review(gateway,own,selection,current,*,priority_only=False):
        assert own['source_pages'] is pages
        if priority_only:
            calls.append('priorities')
            if reject_priority:
                verdict=module.RetainedSelectionCoverage(accepted=False,missing_insight_ids=['c'],
                    prioritized_insight_ids=['c'],reason='Missing an indispensable finding.')
                raise module.SelectionCoverageError('Selection must change.',verdict)
            return
        iid,=own['copy_review_ids']
        barrier.wait(timeout=10)
        calls.append(iid)
        current.validation_warnings.append(ValidationIssue(code='retained_selection_coverage',
            stage='presentation',severity='info',message=json.dumps(dict(input_fingerprint=iid,
                review=dict(accepted=True,page_issues=[])))))
    monkeypatch.setattr(module,'_review_selection_coverage',review)
    monkeypatch.setattr(module,'_coverage_payload',lambda own,*args:(own,{},{}))
    monkeypatch.setattr(retained_copy_review,'copy_review_payload',lambda payload:payload)
    if reject_priority:
        with pytest.raises(module.SelectionCoverageError):
            module.review_selection_coverage(SimpleNamespace(discovery_workers=8),context,selection,result)
        assert calls==['priorities']
    else:
        module.review_selection_coverage(SimpleNamespace(discovery_workers=8),context,selection,result)
        assert calls[0]=='priorities' and set(calls[1:])=={'a','b'}
        audit=json.loads(result.validation_warnings[-1].message)
        assert audit['copy_review_ids']==['a','b'] and not audit['final_presentation_approval']
