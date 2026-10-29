"""Independent source reviews overlap without sharing approval or call budgets."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextvars import ContextVar
import json
from threading import Barrier, Lock
import time

import pytest

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector
from adaptive_document_agent.agent.topic_evidence_review import review_topic_evidence
from adaptive_document_agent.agent.topic_review_output import review_request
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName, PrivacyMode
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import PrivacyViolationError
from tests.test_topic_review_recovery_v203 import selected

scope = ContextVar('review_test_scope', default=None)


class ReviewingClient(MockLLMClient):
    supports_concurrent_requests = True

    def __init__(self, barrier=None, error=None):
        super().__init__()
        self.barrier, self.error = barrier, error
        self.active = self.peak = 0
        self.lock = Lock()
        self.contexts = []

    def generate_text(self, messages, **kwargs):
        payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        with self.lock:
            self.calls.append(payload)
            self.contexts.append(scope.get())
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.barrier:
                self.barrier.wait(timeout=5)
            if self.error:
                raise self.error
            # Complete out of submission order; the audit must remain ordered.
            if payload['topics'][0]['id'] == 'history':
                time.sleep(.03)
            return LLMResponse(text=json.dumps({'decisions': [dict(topic_id=t['id'],
                supported=True, reason='Supported by the complete supplied source.') for t in payload['topics']]}))
        finally:
            with self.lock:
                self.active -= 1


def fixture(client, *, local=False):
    result, lookup, selection = selected()
    selection.topics.append(selection.topics[-1].model_copy(update={'id': 'fourth'}))
    settings = LLMSettings(provider=ProviderName.OLLAMA if local else ProviderName.DEEPSEEK,
        model='test', discovery_workers=2,
        privacy_mode=PrivacyMode.LOCAL_ONLY if local else PrivacyMode.CLOUD)
    return result, lookup, selection, LLMGateway(client, settings)


def test_parallel_reviews_keep_complete_facts_and_stable_audits():
    client = ReviewingClient(Barrier(2))
    result, lookup, selection, gateway = fixture(client)
    original = selection.model_dump()
    token = scope.set('owned-context')
    try:
        actual = review_topic_evidence(selection, lookup, result, gateway, PresentationTopicSelector._validate)
    finally:
        scope.reset(token)
    assert actual.model_dump() == original and client.peak == 2
    assert client.contexts == ['owned-context', 'owned-context']
    audit = json.loads(result.validation_warnings[-1].message)
    assert audit['physical_calls'] == 2 and len(audit['accepted_bindings']) == 4
    assert [a['response']['decisions'][0]['topic_id'] for a in audit['attempts']] == ['history', 'fourth']
    for call in client.calls:
        expected = {o.id for t in call['topics'] for sid in t['series_ids'] for o in lookup[sid]}
        assert {o['id'] for series in call['series'] for o in series['observations']} == expected
        pages = {p['page'] for p in call['source_pages']}
        assert pages | set(call['unavailable_source_pages']) == {p for ps in call['topic_source_pages'].values() for p in ps}


@pytest.mark.parametrize('local,stateful', [(True, False), (False, True)])
def test_local_or_stateful_clients_remain_serial(local, stateful):
    client = ReviewingClient()
    client.supports_concurrent_requests = not stateful
    result, lookup, selection, gateway = fixture(client, local=local)
    assert review_topic_evidence(selection, lookup, result, gateway, PresentationTopicSelector._validate) == selection
    assert client.peak == 1


@pytest.mark.parametrize('error', [PrivacyViolationError('private'), CancelledError('cancelled')])
def test_parallel_privacy_and_cancellation_propagate(error):
    client = ReviewingClient(Barrier(2), error)
    result, lookup, selection, gateway = fixture(client)
    with pytest.raises(type(error)):
        review_topic_evidence(selection, lookup, result, gateway, PresentationTopicSelector._validate)
    audit = json.loads(result.validation_warnings[-1].message)
    assert not audit['accepted_bindings'] and len(client.calls) == 2


def test_budget_reservations_are_atomic(monkeypatch):
    from adaptive_document_agent.agent import topic_review_output as module
    monkeypatch.setattr(module, 'MAX_REVIEW_CALLS', 3)
    class Gateway:
        def generate_structured(self, *args, **kwargs):
            return 'checked'
    budget, lock = {'calls': 0}, Lock()
    def run(_):
        try:
            return review_request(Gateway(), [], object, {}, budget, lock=lock)
        except ValueError:
            return 'exhausted'
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(20)))
    assert results.count('checked') == budget['calls'] == 3


def test_expired_shared_deadline_blocks_all_parallel_requests():
    from adaptive_document_agent.services.analysis_deadline import AnalysisDeadline, AnalysisTimeLimitExceeded
    client = ReviewingClient()
    result, lookup, selection, gateway = fixture(client)
    gateway.run_deadline = AnalysisDeadline(clock=lambda: 901, started_at=0)
    with pytest.raises(AnalysisTimeLimitExceeded):
        review_topic_evidence(selection, lookup, result, gateway, PresentationTopicSelector._validate)
    assert not client.calls
