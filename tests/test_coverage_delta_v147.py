"""Independent coverage requests preserve complete evidence without state echoes."""
from copy import deepcopy
from threading import Barrier, Event, Lock
import json

import pytest

from adaptive_document_agent.agent.coverage_delta_review import TopicCoverageDelta
from adaptive_document_agent.agent.coverage_review_context import compact_context, delta_context, encode, batch_context
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_coverage_review import review_topic_coverage
from adaptive_document_agent.models import PresentationTopicSelection
from tests.test_bounded_topic_coverage import context_fixture
from tests.test_topic_coverage_review import _topic


def payload(messages):
    message = next(m for m in messages if m['role'] == 'user'
                   and 'series_requiring_coverage_decision' in m['content'])
    return json.loads(message['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


def decisions(schema, ids, included=()):
    return schema(coverage_decisions=[dict(series_id=sid, decision='include' if sid in included else 'omit',
        reason='A source-bound recent change qualifies the retained historical finding.' if sid in included
        else 'The source scope does not add a material qualification to the retained question.') for sid in ids])


def force_delta(monkeypatch, size=64):
    from adaptive_document_agent.agent import topic_coverage_review as module
    monkeypatch.setattr(module, 'MAX_REVIEW_DECISIONS', 0)
    monkeypatch.setattr(module, 'MAX_DELTA_DECISIONS', size)


def test_delta_payload_keeps_every_requested_point_and_qualification_without_accepted_grid_echo():
    _, lookup, annual, interim, adverse, raw = context_fixture()
    original = deepcopy(raw)
    raw['source_row_qualifications'] = [dict(series_id=sid, notes=['Literal condition ' + sid])
                                        for sid in lookup]
    from adaptive_document_agent.agent.topic_coverage_review import source_period_views
    raw['same_source_row_period_views'] = source_period_views(lookup)
    compact = compact_context(raw)
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    request = delta_context(compact, selected, [interim, adverse])
    assert 'current_selection' not in request and 'complete_series_catalog' not in request
    assert {r['id'] for r in request['all_extracted_series']} == {interim, adverse}
    assert request['accepted_topic_handles'][0]['series_ids'] == [annual]
    assert {q['series_id'] for q in request['source_row_qualifications']} == {interim, adverse}
    assert request['same_source_row_period_views'] == raw['same_source_row_period_views']
    for row in request['all_extracted_series']:
        facts = [{**row['point_constants'], **dict(zip(row['point_columns'], p))} for p in row['reported_points']]
        expected = lookup[row['id']]
        assert [(f['raw_value'], f['value'], f['period'], f['audited_status']) for f in facts] == [
            (o.raw_value, o.value, o.period, o.audited_status) for o in expected]
    assert original['all_extracted_series'] == raw['all_extracted_series']


def test_479_candidates_receive_eight_complete_delta_requests_without_sampling(monkeypatch):
    force_delta(monkeypatch)
    from tests.test_topic_coverage_review import _observation
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    result, _, annual, _, _, raw = context_fixture()
    for index in range(477):
        result.observations.extend([_observation(f'Process series {index}', 'FY2022', 20),
                                    _observation(f'Process series {index}', 'FY2023', 60)])
    directory, lookup = series_directory(result)
    raw['all_extracted_series'] = [[entry[k] for k in raw['series_columns']] for entry in directory]
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    candidates = [sid for sid in lookup if sid != annual]
    assert len(candidates) == 479
    class Gateway:
        def __init__(self): self.requests = []
        def generate_structured(self, messages, schema, **kwargs):
            data = payload(messages)
            assert schema is TopicCoverageDelta
            self.requests.append(data)
            return decisions(schema, data['series_requiring_coverage_decision'])
    gateway = Gateway()
    snapshot = result.model_dump(include={'observations', 'presentation_topics', 'charts'})
    final = review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    requested = [sid for r in gateway.requests for sid in r['series_requiring_coverage_decision']]
    assert requested == candidates and len(set(requested)) == 479
    assert len(gateway.requests) == 8
    compact = compact_context(raw)
    expected_rows = {row['id']: row for row in compact['all_extracted_series'] if row['id'] in candidates}
    actual_rows = {}
    for request in gateway.requests:
        for cells in request['all_extracted_series']:
            row = dict(zip(request['series_columns'], cells))
            row['point_constants'] = {request['point_field_names'][i]: value for i, value in row['point_constants']}
            row['point_columns'] = [request['point_field_names'][i] for i in row['point_columns']]
            actual_rows[row['id']] = row
    assert actual_rows == expected_rows  # Every interior point and source field, not only series IDs.
    old_chars = sum(len(encode(batch_context(compact, selected, candidates[i:i+32])))
                    for i in range(0, 479, 32))
    new_chars = sum(len(encode(request)) for request in gateway.requests)
    assert new_chars < old_chars * .6
    audit = json.loads(result.validation_warnings[-1].message)
    assert len(audit['review']['coverage_decisions']) == 479
    assert audit['calls_used'] == 8 and audit['merge'] is None
    assert final.topics == selected.topics
    assert result.model_dump(include={'observations', 'presentation_topics', 'charts'}) == snapshot


def test_parallel_deltas_share_one_immutable_snapshot_and_merge_in_source_order(monkeypatch):
    force_delta(monkeypatch, size=1)
    result, lookup, annual, interim, adverse, raw = context_fixture()
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    barrier = Barrier(2)
    class Gateway:
        discovery_workers = 2
        def __init__(self): self.requests, self.lock = [], Lock()
        def generate_structured(self, messages, schema, **kwargs):
            data = payload(messages)
            with self.lock: self.requests.append(data)
            if schema is TopicCoverageDelta:
                assert data['accepted_topic_handles'] == [dict(id='history', title=selected.topics[0].title,
                    question=selected.topics[0].question, takeaway='', caveats=[], series_ids=[annual])]
                barrier.wait(timeout=5)
                return decisions(schema, data['series_requiring_coverage_decision'], [interim, adverse])
            assert 'accepted_topic_handles' not in data
            assert set(data['selectable_series_ids']) == {annual, interim, adverse}
            assert 'complete_series_catalog' not in data
            return schema(topics=[_topic(annual), _topic(interim, 'recent'), _topic(adverse, 'constraint')],
                coverage_decisions=[d.model_dump() for d in decisions(TopicCoverageDelta, [interim, adverse], [interim, adverse]).coverage_decisions])
    gateway = Gateway()
    final = review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    assert {sid for topic in final.topics for sid in topic.series_ids} == {annual, interim, adverse}
    audit = json.loads(result.validation_warnings[-1].message)
    assert [d['series_id'] for d in audit['review']['coverage_decisions']] == [sid for sid in lookup if sid != annual]
    assert audit['workers'] == 2 and audit['calls_used'] == 3
    assert selected.topics == [_topic(annual)] and not selected.omissions


@pytest.mark.parametrize('fault', ['lost_original', 'false_include', 'deferred', 'wrong_period'])
def test_invalid_final_merge_rolls_back_every_provisional_delta(monkeypatch, fault):
    force_delta(monkeypatch, size=1)
    result, lookup, annual, interim, adverse, raw = context_fixture()
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            data = payload(messages)
            if schema is TopicCoverageDelta:
                return decisions(schema, data['series_requiring_coverage_decision'], [interim])
            topics = [_topic(annual), _topic(interim, 'recent')]
            if fault == 'lost_original': topics = topics[1:]
            elif fault == 'false_include': topics = topics[:1]
            elif fault == 'deferred': topics.append(_topic(adverse, 'constraint'))
            elif fault == 'wrong_period': topics[1].takeaway = 'The result rose in FY2037.'
            return schema(topics=topics, coverage_decisions=[d.model_dump() for d in decisions(TopicCoverageDelta, [interim], [interim]).coverage_decisions])
    final = review_topic_coverage(selected, result, lookup, set(), raw, Gateway(), PresentationTopicSelector._validate)
    assert final == selected and selected.omissions == []
    audit = json.loads(result.validation_warnings[-1].message)
    assert result.validation_warnings[-1].code == 'presentation_topic_coverage_unresolved'
    assert len(audit['batches']) == 2 and audit['merge']['attempts'][-1]['validation_error']


def test_merge_may_omit_provisional_addition_but_must_record_model_reason(monkeypatch):
    force_delta(monkeypatch)
    result, lookup, annual, interim, adverse, raw = context_fixture()
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    class Gateway:
        def generate_structured(self, messages, schema, **kwargs):
            ids = payload(messages)['series_requiring_coverage_decision']
            if schema is TopicCoverageDelta: return decisions(schema, ids, [interim])
            return schema(topics=selected.topics, coverage_decisions=[d.model_dump() for d in decisions(TopicCoverageDelta, ids).coverage_decisions])
    final = review_topic_coverage(selected, result, lookup, set(), raw, Gateway(), PresentationTopicSelector._validate)
    assert final.topics == selected.topics
    audit = json.loads(result.validation_warnings[-1].message)
    assert {d['series_id']: d['decision'] for d in audit['review']['coverage_decisions']} == {interim:'omit', adverse:'omit'}
    assert audit['batches'][0]['review']['coverage_decisions'][0]['decision'] == 'include'


def test_transport_failure_retains_completed_batch_audit_without_semantic_regeneration(monkeypatch):
    from adaptive_document_agent.services.llm.exceptions import LLMTransportError
    force_delta(monkeypatch, size=1)
    result, lookup, annual, _, _, raw = context_fixture()
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    class Gateway:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            if self.calls == 2: raise LLMTransportError('Provider unavailable')
            return decisions(schema, payload(messages)['series_requiring_coverage_decision'])
    gateway = Gateway()
    assert review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate) == selected
    assert gateway.calls == 2
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['batches'][0]['review'] and audit['batches'][1]['attempts'][0]['request_error']
    assert len(audit['unreviewed_series_ids']) == 1


def test_local_only_gateway_keeps_delta_review_serial_and_never_uses_another_provider(monkeypatch):
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, PrivacyMode, ProviderName
    force_delta(monkeypatch, size=1)
    result, lookup, annual, _, _, raw = context_fixture()
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    ids = [sid for sid in lookup if sid != annual]
    replies = [decisions(TopicCoverageDelta, [sid]).model_dump() for sid in ids]
    client = MockLLMClient(replies)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.OLLAMA, model='local',
        base_url='http://127.0.0.1:11434', privacy_mode=PrivacyMode.LOCAL_ONLY, discovery_workers=4))
    final = review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    assert final.topics == selected.topics and len(client.calls) == 2
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['workers'] == 1 and gateway.client is client
    assert gateway.settings.privacy_mode == PrivacyMode.LOCAL_ONLY
    assert all(u['provider'] == 'mock' and u['operation'] == 'TopicCoverageDelta' for u in gateway.usage)


def guarded_gateway(client, failed, *, workers=1):
    """Exercise the production guard; every provider operation is a local mock."""
    from adaptive_document_agent.agent.introduction_checkpoint import (
        IntroductionGuardedGateway, IntroductionVerificationFailed)
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, ProviderName
    source_failure, observed = ValueError('Mandatory source review rejected its current draft'), []
    class Prepared:
        def raise_if_failed(self):
            if failed.is_set():
                raise source_failure
    class Guard(IntroductionGuardedGateway):
        def check(self):
            try:
                super().check()
            except IntroductionVerificationFailed as exc:
                observed.append(exc)
                raise
    actual = LLMGateway(client, LLMSettings(provider=ProviderName.DEEPSEEK,
                                          discovery_workers=workers), cache_enabled=False)
    return Guard(actual, Prepared()), observed, source_failure


@pytest.mark.parametrize('failure_phase', ['delta', 'merge'])
def test_mandatory_intro_guard_keeps_unresolved_history_and_reraises_exact_failure(monkeypatch, failure_phase):
    from adaptive_document_agent.agent.introduction_checkpoint import IntroductionVerificationFailed
    from adaptive_document_agent.services.llm import MockLLMClient
    from adaptive_document_agent.services.llm.base import LLMResponse
    force_delta(monkeypatch, size=1)
    result, lookup, annual, interim, _, raw = context_fixture()
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    snapshot, original = result.model_dump(include={'observations', 'presentation_topics', 'charts'}), deepcopy(selected)
    failed = Event()
    class Client(MockLLMClient):
        def generate_text(self, messages, **kwargs):
            self.calls.append(messages)
            ids = payload(messages)['series_requiring_coverage_decision']
            reply = decisions(TopicCoverageDelta, ids, [interim])
            if len(self.calls) == (1 if failure_phase == 'delta' else 2):
                failed.set()
            return LLMResponse(text=reply.model_dump_json())
    client = Client()
    gateway, observed, source_failure = guarded_gateway(client, failed)
    with pytest.raises(IntroductionVerificationFailed) as caught:
        review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    assert caught.value is observed[0] and caught.value.__cause__ is source_failure
    assert len(client.calls) == (1 if failure_phase == 'delta' else 2)
    assert selected == original and result.model_dump(include={'observations', 'presentation_topics', 'charts'}) == snapshot
    issue = result.validation_warnings[-1]
    audit = json.loads(issue.message)
    assert issue.code == 'presentation_topic_coverage_unresolved'
    assert audit['status'] == 'cancelled_mandatory_introduction' and audit['semantic_approval'] is False
    assert audit['original_selection'] == original.model_dump(mode='json') and 'review' not in audit
    assert audit['batches'][0]['review']['coverage_decisions'][0]['decision'] == 'include'
    blocked = audit['batches'][1] if failure_phase == 'delta' else audit['merge']
    assert blocked['attempts'][0]['error_type'] == 'IntroductionVerificationFailed'
    assert blocked['attempts'][0]['request_status'] == 'blocked_by_mandatory_introduction'
    assert len(audit['unreviewed_series_ids']) == (1 if failure_phase == 'delta' else 0)


def test_queued_guard_failure_drains_and_records_inflight_deltas_without_committing_them(monkeypatch):
    from adaptive_document_agent.agent.introduction_checkpoint import IntroductionVerificationFailed
    from adaptive_document_agent.services.llm import MockLLMClient
    from adaptive_document_agent.services.llm.base import LLMResponse
    force_delta(monkeypatch, size=1)
    result, lookup, annual, interim, _, raw = context_fixture(extra=1)
    selected = PresentationTopicSelection(topics=[_topic(annual)])
    original = deepcopy(selected)
    snapshot = result.model_dump(include={'observations', 'presentation_topics', 'charts'})
    failed, barrier = Event(), Barrier(2)
    class Client(MockLLMClient):
        supports_concurrent_requests = True
        def generate_text(self, messages, **kwargs):
            self.calls.append(messages)
            ids = payload(messages)['series_requiring_coverage_decision']
            barrier.wait(timeout=3)
            failed.set()
            return LLMResponse(text=decisions(TopicCoverageDelta, ids, [interim]).model_dump_json())
    client = Client()
    gateway, observed, source_failure = guarded_gateway(client, failed, workers=2)
    with pytest.raises(IntroductionVerificationFailed) as caught:
        review_topic_coverage(selected, result, lookup, set(), raw, gateway, PresentationTopicSelector._validate)
    assert caught.value is observed[0] and caught.value.__cause__ is source_failure
    assert len(client.calls) == 2
    assert selected == original and result.model_dump(include={'observations', 'presentation_topics', 'charts'}) == snapshot
    audit = json.loads(result.validation_warnings[-1].message)
    assert len([batch for batch in audit['batches'] if 'review' in batch]) == 2
    assert audit['cancelled_batch_numbers'] == [3] and len(audit['unreviewed_series_ids']) == 1
    assert audit['batches'][2]['attempts'][0]['request_status'] == 'blocked_by_mandatory_introduction'
    assert audit['merge'] is None and audit['semantic_approval'] is False and 'review' not in audit
