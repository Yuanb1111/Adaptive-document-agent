"""Oversized review and incorrect references must recover without invented evidence."""
import json
from copy import deepcopy
import pytest
from adaptive_document_agent.agent.coverage_delta_review import TopicCoverageDelta
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_coverage_review import review_topic_coverage
from adaptive_document_agent.agent.topic_reference_repair import repair_unknown_references
from tests.test_coverage_delta_v147 import payload, decisions, force_delta
from tests.test_coverage_merge_encoding import _fixture
from tests.test_topic_coverage_review import _topic
from adaptive_document_agent.agent.coverage_review_context import compact_context, merge_context
from adaptive_document_agent.agent.coverage_merge_encoding import encode_merge_context


def test_oversized_proposals_reduce_with_complete_facts_and_keep_original(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review as module
    force_delta(monkeypatch, size=4)
    result, lookup, selected, raw = _fixture()
    before = deepcopy(selected)
    ids = [sid for sid in lookup if sid not in selected.topics[0].series_ids]
    budget = len(encode_merge_context(merge_context(compact_context(raw), selected, ids, []))) - 500
    monkeypatch.setattr(module, 'MAX_REVIEW_CHARACTERS', budget)
    requested, reduced = [], []
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            data = payload(messages)
            wanted = data['series_requiring_coverage_decision']
            assert len(messages[-1]['content']) < budget
            if 'hierarchical_reduction' in data:
                assert schema is TopicCoverageDelta
                assert len(data['all_extracted_series']) == len(wanted)
                reduced.extend(wanted)
                return decisions(schema, wanted)  # Model-authored source-aware omissions.
            if schema is TopicCoverageDelta:
                requested.extend(wanted)
                return decisions(schema, wanted, wanted)
            return schema(topics=selected.topics, coverage_decisions=[
                d.model_dump() for d in decisions(TopicCoverageDelta, wanted).coverage_decisions])
    final = review_topic_coverage(selected, result, lookup, set(), raw, Gateway(), PresentationTopicSelector._validate)
    audit = json.loads(result.validation_warnings[-1].message)
    assert result.validation_warnings[-1].code == 'presentation_topic_coverage_review'
    assert requested == ids and set(reduced) <= set(ids) and reduced
    assert final.topics == selected.topics and selected == before
    assert audit['merge']['reductions'] and audit['calls_used'] <= module.MAX_REVIEW_CALLS
    assert len(audit['review']['coverage_decisions']) == len(ids)
    assert all(d['decision'] == 'omit' and d['reason'] for d in audit['review']['coverage_decisions'])


def test_reduced_proposal_can_be_selected_only_after_full_fact_final_merge(monkeypatch):
    from adaptive_document_agent.agent import topic_coverage_review as module
    force_delta(monkeypatch, size=4)
    result, lookup, selected, raw = _fixture()
    ids = [sid for sid in lookup if sid not in selected.topics[0].series_ids]
    raw['source_row_qualifications'] = [dict(series_id=sid, notes=[dict(
        label=lookup[sid][0].metric_original, text=sid + ' Literal source condition.' * 35,
        page=234, table_id='source', marker='1')]) for sid in ids]
    monkeypatch.setattr(module, 'MAX_REVIEW_CHARACTERS',
        len(encode_merge_context(merge_context(compact_context(raw), selected, ids, []))) - 500)
    accepted=[]
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            data=payload(messages);wanted=data['series_requiring_coverage_decision']
            if 'hierarchical_reduction' in data:
                return decisions(schema,wanted,wanted[:1] if len(wanted) >= 3 else [])
            if schema is TopicCoverageDelta:
                return decisions(schema,wanted,wanted)
            assert wanted
            accepted.extend(wanted[:1])
            assert set(data['selectable_series_ids']) == set(selected.topics[0].series_ids) | set(wanted)
            return schema(topics=[*selected.topics,_topic(wanted[0],'new-evidence')],
                coverage_decisions=[d.model_dump() for d in decisions(TopicCoverageDelta,wanted,wanted[:1]).coverage_decisions])
    final=review_topic_coverage(selected,result,lookup,set(),raw,Gateway(),PresentationTopicSelector._validate)
    audit=json.loads(result.validation_warnings[-1].message)
    assert result.validation_warnings[-1].code=='presentation_topic_coverage_review', audit.get('reason')
    assert {sid for t in final.topics for sid in t.series_ids} == set(selected.topics[0].series_ids) | set(accepted)
    assert audit['merge']['status']=='complete'
    ledger={d['series_id']:d for d in audit['review']['coverage_decisions']}
    assert len(ledger)==len(ids) and ledger[accepted[0]]['decision']=='include'
    assert all(d['reason'] for d in ledger.values())


@pytest.mark.parametrize('fault', ['', 'duplicate', 'noncatalog', 'known_reference'])
def test_reference_repair_is_model_owned_atomic_and_does_not_change_valid_ids(fault):
    result, lookup, selection, _ = _fixture()
    known = selection.topics[0].series_ids[0]
    target = next(sid for sid in lookup if sid != known)
    selection.topics[0].series_ids.append('mistyped-reference')
    original = deepcopy(selection)
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            data = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert len(data['catalog']) == len(lookup)
            binding = dict(unknown_id='mistyped-reference', series_id=target, reason='Same intended source metric and period scope.')
            if fault == 'duplicate': binding['series_id'] = known
            if fault == 'noncatalog': binding['series_id'] = 'invented'
            if fault == 'known_reference': binding['unknown_id'] = known
            return schema(bindings=[binding])
    repair_unknown_references(selection, lookup, result, Gateway())
    if fault:
        assert selection == original
    else:
        assert selection.topics[0].series_ids == [known, target]
    assert json.loads(result.validation_warnings[-1].message)['status'] == ('unresolved' if fault else 'bound')
