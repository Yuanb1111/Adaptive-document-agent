"""A priority correction authors only changed pages, then earns fresh review."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent import retained_analysis as retained
from adaptive_document_agent.agent.retained_priority_patch import priority_patch
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.test_retained_analysis_v216 import gateway
from tests.test_retained_source_citations import fixture


def proposal():
    result,_,selection = fixture()
    original=selection.ordered_insight_ids[0]
    result.insights.append(result.insights[0].model_copy(update={'id':'additional'}))
    draft=selection.model_dump(mode='json',exclude_none=True)
    draft['decisions'].append(dict(insight_id='additional',decision='omit',reason='Lower priority.'))
    added=dict(insight_id='additional',decision='include',reason='Material counterevidence.',
               page=deepcopy(draft['decisions'][0]['page']))
    return result,original,draft,added


def test_missing_priority_only_authors_new_page_and_still_reviews_full_selection():
    result,iid,draft,added=proposal()
    before=deepcopy(result)
    llm=gateway([draft,dict(accepted=False,missing_insight_ids=['additional'],
        prioritized_insight_ids=[iid,'additional'],reason='Retain this material counterpoint.'),
        dict(reasons={'additional':added['reason']},pages={'additional':added['page']}),
        dict(accepted=True,reason='Complete fresh coverage review.')])
    retained.select_retained_analysis(llm,result)
    selected=retained.selected_record(result)['selection']
    assert selected['decisions'][0]==draft['decisions'][0]
    assert selected['decisions'][1]==added
    assert [u['operation'] for u in llm.usage]==['SourceAuthoredAnalysisSelection',
        'RetainedSelectionCoverage','PriorityPagePatch','RetainedSelectionCoverage']
    assert 'editable_decision_ids' in str(llm.client.calls[2])
    for field in ('document','observations','analysis_results','insights'):
        assert getattr(result,field)==getattr(before,field)


@pytest.mark.parametrize('defect',['missing','missing_page','foreign','changed_frozen','wrong_priority'])
def test_invalid_delta_cannot_modify_frozen_page_or_skip_requested_decisions(defect):
    result,iid,draft,added=proposal()
    response=dict(reasons={'additional':added['reason']},pages={'additional':deepcopy(added['page'])})
    if defect=='missing':response['reasons']={}
    elif defect=='missing_page':response['pages']={}
    elif defect=='foreign':response['reasons']['unknown']='Foreign decision.'
    elif defect=='changed_frozen':
        frozen=deepcopy(draft['decisions'][0]);frozen['page']['message']='A different claim.'
        response['pages'][iid]=frozen['page']
    else:
        response['pages']={iid:deepcopy(added['page'])}
    llm=gateway([response]);before=deepcopy(draft)
    with pytest.raises((ValueError,LLMResponseError)):
        priority_patch(llm,[],retained.SourceAuthoredAnalysisSelection,result,1,draft,
                       [iid,'additional'],{})
    assert draft==before and retained.selected_record(result) is None


def test_copy_transport_cannot_return_a_new_selection_order():
    from adaptive_document_agent.agent.retained_priority_patch import PriorityPagePatch
    with pytest.raises(ValueError,match='Extra inputs'):
        PriorityPagePatch.model_validate(dict(reasons={},pages={},ordered_insight_ids=['other']))


@pytest.mark.parametrize('decision,page',[('include',None),('omit',dict(
    title='An omitted page',message='This cannot be published.'))])
def test_source_selection_schema_binds_page_presence_to_the_decision(decision,page):
    response=dict(decisions=[dict(insight_id='owned',decision=decision,
        reason='Synthetic source decision.',page=page)],ordered_insight_ids=['owned'])
    with pytest.raises(ValueError):
        retained.SourceAuthoredAnalysisSelection.model_validate(response)


def test_reviewed_membership_is_compiled_without_reasking_the_copy_writer():
    result,iid,draft,added=proposal()
    before=deepcopy(draft)
    llm=gateway([dict(reasons={iid:'Replaced by the broader finding.',
        'additional':'Material broader finding.'},pages={'additional':added['page']})])
    corrected=priority_patch(llm,[],retained.SourceAuthoredAnalysisSelection,result,1,draft,
                             ['additional'],{})
    assert corrected.ordered_insight_ids==['additional']
    decisions={d.insight_id:d for d in corrected.decisions}
    assert decisions[iid].decision=='omit' and decisions[iid].page is None
    assert decisions['additional'].decision=='include'
    assert draft==before and retained.selected_record(result) is None


def test_priority_order_alone_needs_no_retranscription_request():
    result,iid,draft,added=proposal()
    draft['decisions'][1]=added;draft['ordered_insight_ids'].append('additional')
    llm=gateway([])
    selection=priority_patch(llm,[],retained.SourceAuthoredAnalysisSelection,result,1,draft,
                             ['additional',iid],{})
    assert selection.ordered_insight_ids==['additional',iid] and not llm.usage
    assert selection.model_dump(mode='json',exclude_none=True)['decisions']==draft['decisions']
