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


@pytest.mark.parametrize('slot', ['context-1', 'context-01', None])
def test_owned_review_routes_description_correction_and_rechecks_full_evidence(monkeypatch, slot):
    from adaptive_document_agent.agent import retained_analysis, retained_source_authoring_parallel
    from adaptive_document_agent.agent.reported_source_context import QualifiedSourceCopy
    from tests.test_retained_description_fidelity import accounts

    result, _, selection = fixture()
    owner, = selection.ordered_insight_ids
    page = selection.decisions[0].page
    proofs = ['Management describes how the orders are received.',
              'The company reports a larger share of orders arriving early.']
    result.document.pages[0].text += '\n' + '\n'.join(proofs)
    page.source_context = [
        QualifiedSourceCopy(scope='orders', description='Describes how orders are received.',
                            quote=dict(page=234, text=proofs[0])),
        QualifiedSourceCopy(scope='order timing', description='Reports earlier orders.',
                            quote=dict(page=234, text=proofs[1])),
    ]
    expected = page.model_copy(deep=True)
    replacement = 'Reports a larger share of orders arriving early.'
    expected.source_context[1].description = replacement
    original_inputs = result.model_dump(include={'document', 'observations', 'insights', 'analysis_results'})
    objection = dict(insight_id=owner, reason='Clarify that the share of orders changed.')
    if slot is not None:
        objection['description_edits'] = {slot: objection['reason']}

    scoped = slot == 'context-1'
    writer_reply = {'context-1': replacement} if scoped else dict(
        message=None, source_context=None, source_context_edits={'context-1': replacement},
        companion_ids=[], context_evidence=[])
    llm = gateway([
        dict(accepted=True, prioritized_insight_ids=[], reason='Selection covers the source.'),
        dict(accepted=False, page_issues=[objection], reason='The order mix needs clarification.'),
        writer_reply, dict(accepted=True, reason='The revised order mix matches the source.'), accounts(expected),
    ])
    monkeypatch.setattr(type(llm), 'discovery_workers', property(lambda self: 8))
    monkeypatch.setattr(retained_source_authoring_parallel, 'select_owned_source_pages', lambda *args: selection)

    retained_analysis.select_retained_analysis(llm, result)

    assert [entry['operation'] for entry in llm.usage] == [
        'RetainedPriorityCoverage', 'RetainedSelectionCoverage',
        'RetainedDescriptionRevision' if scoped else 'RetainedPageRevisions', 'RetainedSelectionCoverage',
        'RetainedDescriptionFidelity']
    selected, = retained_analysis.selected_record(result)['selection']['decisions']
    assert selected['page'] == expected.model_dump(mode='json', exclude_none=True)
    assert result.model_dump(include=set(original_inputs)) == original_inputs
    packets = [decode_records(json.loads(call[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]))
               for call in llm.client.calls]
    _, before, writer, after, fidelity = packets
    assert fidelity['context-1']['description'] == replacement
    assert before['source_context_edit_slots'][owner] == {
        'context-0': {'scope': 'orders', 'description': 'Describes how orders are received.'},
        'context-1': {'scope': 'order timing', 'description': 'Reports earlier orders.'},
    }
    assert after['source_context_edit_slots'][owner]['context-1']['description'] == replacement
    assert 'revised_source_descriptions' not in before
    assert after['revised_source_descriptions'] == {
        owner: {'context-1': {'audience_text': 'For order timing, the source reports a larger share of orders arriving early.',
                              'source_pages': [234]}}}
    if scoped:
        assert list(writer['addressed_descriptions']) == ['context-1']
        assert writer['addressed_descriptions']['context-1']['literal_proof'] == [dict(page=234, text=proofs[1])]
    else:
        assert owner in writer['pages_to_correct']
    assert before['retained_proofs'] == after['retained_proofs']
    assert before['source_pages'] == after['source_pages']
    assert before['proposed_selection']['decisions'][0]['page']['source_context'][1]['description'] == 'Reports earlier orders.'
    assert after['proposed_selection']['decisions'][0]['page']['source_context'][1]['description'] == replacement


@pytest.mark.parametrize('reject_priority',[False,True])
def test_fast_initial_review_requires_priority_verdict_then_every_owned_source_verdict(monkeypatch,reject_priority):
    from adaptive_document_agent.agent import retained_copy_review
    from tests.test_retained_copy_review_parallel import Result
    result=Result();selection=SimpleNamespace(ordered_insight_ids=['a','b'])
    pages=[dict(page=1,text='Complete source'),dict(page=2,text='Continued qualification')]
    context=dict(source_pages=pages,copy_review_ids=[])
    calls=[];barrier=Barrier(2)
    def review(gateway,own,selection,current,*,priority_only=False,prepared=None):
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


def test_owned_coverage_builds_evidence_once_per_round_and_preserves_every_reviewer_packet(monkeypatch):
    from adaptive_document_agent.agent import coverage_verdict_format
    from adaptive_document_agent.agent.retained_analysis import fingerprint,selection_context
    from adaptive_document_agent.agent.retained_copy_review import copy_review_payload,source_first_wire_payload

    result,_,selection=fixture()
    sibling='other-selected-finding'
    result.insights.append(result.insights[0].model_copy(update={'id':sibling}))
    selection.decisions.append(selection.decisions[0].model_copy(deep=True,update={'insight_id':sibling}))
    selection.ordered_insight_ids.append(sibling)
    context={**selection_context(result,source_authoring=True),'copy_review_ids':list(selection.ordered_insight_ids)}
    original=module._coverage_payload
    builds=[]
    def counted(current,*args):
        builds.append(list(current['copy_review_ids']))
        return original(current,*args)
    monkeypatch.setattr(module,'_coverage_payload',counted)

    requests={}
    def verdict(gateway,messages,schema,audit,*args,**kwargs):
        wire=decode_records(json.loads(messages[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0]))
        iid,=wire['copy_review_ids']
        requests[iid]=wire
        audit['output_attempts']=[]
        return schema(accepted=True,reason='Exact source review.')
    monkeypatch.setattr(coverage_verdict_format,'complete_coverage_verdict',verdict)

    for round_number in (1,2):
        selection.decisions[0].page.message=f'Reporting round {round_number}.'
        expected={iid:original({**context,'copy_review_ids':[iid]},selection,result)[0]
                  for iid in selection.ordered_insight_ids}
        module.review_selection_coverage(SimpleNamespace(discovery_workers=8),context,selection,result)
        audits=[json.loads(issue.message) for issue in result.validation_warnings[-3:]]
        assert len(builds)==round_number
        assert audits[-1]['copy_review_ids']==context['copy_review_ids']
        assert audits[-1]['input_fingerprint']==fingerprint(original(context,selection,result)[0])
        for audit in audits[:-1]:
            iid,=audit['copy_review_ids']
            assert audit['input_fingerprint']==fingerprint(expected[iid])
            assert requests[iid]==source_first_wire_payload(copy_review_payload(expected[iid]))
            assert requests[iid]['source_pages']==context['source_pages']
            assert audit['copy_review_packet']['wire_fingerprint']==fingerprint(requests[iid])


@pytest.mark.parametrize('accept_last', [True, False])
def test_last_unresolved_owner_in_a_reviewed_batch_gets_one_final_correction(monkeypatch, accept_last):
    from adaptive_document_agent.agent import (
        coverage_verdict_format, retained_analysis, retained_page_revision, retained_source_authoring_parallel,
    )
    from adaptive_document_agent.agent.retained_page_sources import RetainedPage

    result, _, selection = fixture()
    owner = selection.ordered_insight_ids[0]
    sibling = 'another-finding'
    result.insights.append(result.insights[0].model_copy(update={'id': sibling}))
    selection.decisions.append(selection.decisions[0].model_copy(deep=True, update={'insight_id': sibling}))
    selection.ordered_insight_ids.append(sibling)
    monkeypatch.setattr(retained_source_authoring_parallel, 'select_owned_source_pages', lambda *args: selection)

    revisions = []
    wording = ['The source reports revenue.', 'The company reports revenue.',
               'The report presents revenue.', 'The issuer discloses revenue.']

    def revise(gateway, result, packet, aliases, draft, issues, **kwargs):
        revised = {}
        for decision in draft['decisions']:
            iid = decision['insight_id']
            if iid in issues:
                revised[iid] = RetainedPage.model_validate({**decision['page'], 'message': wording[len(revisions)]})
        revisions.append(revised)
        return revised

    def verdict(gateway, messages, schema, audit, *args, **kwargs):
        audit['output_attempts'] = []
        packet = decode_records(json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0]))
        if not packet['copy_review_ids']:
            return schema(accepted=True, prioritized_insight_ids=[], reason='The selected findings cover the source.')
        iid, = packet['copy_review_ids']
        accepted = (iid == sibling and len(revisions) == 3) or (len(revisions) == 4 and accept_last)
        return schema(accepted=accepted, reason='Checked this finding against the source.',
                      page_issues=[] if accepted else [dict(insight_id=iid, reason='Clarify the attribution.')])

    monkeypatch.setattr(retained_page_revision, 'revise_retained_pages', revise)
    monkeypatch.setattr(coverage_verdict_format, 'complete_coverage_verdict', verdict)
    gateway = SimpleNamespace(discovery_workers=8)
    if accept_last:
        retained_analysis.select_retained_analysis(gateway, result)
        final_draft = retained_analysis.selected_record(result)['selection']
    else:
        with pytest.raises(ValueError, match='Clarify the attribution'):
            retained_analysis.select_retained_analysis(gateway, result)
        assert retained_analysis.selected_record(result) is None
        final_draft = json.loads(result.validation_warnings[-1].message)['rejected_draft']

    assert [set(batch) for batch in revisions] == [{owner, sibling}] * 3 + [{owner}]
    final_pages = {decision['insight_id']: decision['page'] for decision in final_draft['decisions']}
    assert final_pages[sibling] == revisions[2][sibling].model_dump(mode='json', exclude_none=True)
    assert final_pages[owner] == revisions[3][owner].model_dump(mode='json', exclude_none=True)
    reviews = [json.loads(w.message) for w in result.validation_warnings if w.code == 'retained_selection_coverage']
    assert reviews[-1]['copy_review_ids'] == [owner]
    assert reviews[-1]['review']['accepted'] is accept_last
