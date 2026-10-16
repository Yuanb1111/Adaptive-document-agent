"""Use gateway capacity without changing candidate decisions or truncation recovery."""
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock, get_ident

import pytest
from pydantic import BaseModel

from adaptive_document_agent.agent.value_scorer import AnalysisValueScorer
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, PrivacyMode, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMTransportError
from adaptive_document_agent.services.llm.usage import LLMUsage
from tests.test_candidate_scoring_batches import BatchClient, score_fixture


class BackgroundAnswer(BaseModel):
    value: int = 1


class ConcurrentClient(BatchClient):
    supports_concurrent_requests = True

    def __init__(self, payload, expected):
        super().__init__(payload)
        self.expected = expected
        self.background_started = Event()
        self.release = Event()
        self.lock = Lock()
        self.active = self.scoring_active = self.peak = self.scoring_peak = 0

    def generate_structured(self, messages, response_model, **kwargs):
        scoring = response_model is not BackgroundAnswer
        with self.lock:
            self.active += 1
            self.scoring_active += int(scoring)
            self.peak = max(self.peak, self.active)
            self.scoring_peak = max(self.scoring_peak, self.scoring_active)
            if not scoring:
                self.background_started.set()
            if self.scoring_active == self.expected:
                self.release.set()
        try:
            assert self.release.wait(3), 'Scoring did not use the available gateway capacity'
            if not scoring:
                return BackgroundAnswer(), LLMResponse(text='{"value":1}')
            return super().generate_structured(messages, response_model, **kwargs)
        finally:
            with self.lock:
                self.active -= 1
                self.scoring_active -= int(scoring)


def make_gateway(client, *, local=False):
    return LLMGateway(client, LLMSettings(provider=ProviderName.OLLAMA if local else ProviderName.DEEPSEEK,
        privacy_mode=PrivacyMode.LOCAL_ONLY if local else PrivacyMode.CLOUD,
        discovery_workers=4))


@pytest.mark.parametrize('reserved,expected', [(0, 4), (1, 3)])
def test_all_available_scoring_slots_preserve_full_context_ranking_reasons_and_source_order(reserved, expected):
    candidates, index, profile, original_client, baseline_gateway = score_fixture(80)
    source = deepcopy(candidates)
    baseline = AnalysisValueScorer(baseline_gateway).score(candidates, index, profile)
    client = ConcurrentClient(original_client.payload, expected)
    gateway = make_gateway(client)
    progress, caller = [], get_ident()
    with ThreadPoolExecutor(max_workers=1) as pool:
        if reserved:
            background = pool.submit(gateway.generate_structured, [], BackgroundAnswer, stage='presentation')
            assert client.background_started.wait(3)
        actual = AnalysisValueScorer(gateway).score(candidates, index, profile,
            reserved_workers=reserved, progress=lambda value: progress.append((get_ident(), value)))
        if reserved:
            assert background.result(timeout=3) == BackgroundAnswer()
    assert client.scoring_peak == expected and client.peak == 4
    assert client.active == 0 and len(client.targets) == 4
    assert candidates == source
    assert [score.model_dump(exclude={'semantic_audit'}) for score in actual] == [
        score.model_dump(exclude={'semantic_audit'}) for score in baseline]
    audits = actual[0].semantic_audit.response_audit.batches
    expected_ids = [item for batch in baseline[0].semantic_audit.response_audit.batches for item in batch.candidate_ids]
    assert [item for batch in audits for item in batch.candidate_ids] == expected_ids
    assert [batch.model_dump() for batch in audits] == [
        batch.model_dump() for batch in baseline[0].semantic_audit.response_audit.batches]
    assert all(owner == caller for owner, _ in progress)
    assert [message for _, message in progress] == [f'Scoring analysis candidates ({i}/4)' for i in range(5)]
    for messages in client.calls:
        wire = ast.literal_eval(next(message['content'] for message in messages
            if message['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>')).split('\n', 1)[1].rsplit('\n', 1)[0])
        assert len(wire['candidates']) == 80


@pytest.mark.parametrize('local,stateful', [(True, False), (False, True)])
@pytest.mark.parametrize('reserved', [0, 1, 4])
def test_local_and_stateful_clients_remain_serial_even_with_four_configured_slots(local, stateful, reserved):
    candidates, _, profile, original_client, _ = score_fixture(80)
    client = ConcurrentClient(original_client.payload, 1)
    client.supports_concurrent_requests = not stateful
    gateway = make_gateway(client, local=local)
    assert gateway.discovery_workers == 1
    batches, audits = AnalysisValueScorer(gateway)._semantic_batches(candidates, profile, reserved_workers=reserved)
    assert len(batches) == len(audits) == len(client.targets) == 4
    assert client.scoring_peak == client.peak == 1
    assert [identifier for ids in client.targets for identifier in ids] == [candidate.id for candidate in candidates]


@pytest.mark.parametrize('reserved', [-1, True, 1.5, '1'])
def test_invalid_reserved_capacity_never_reaches_model(reserved):
    candidates, _, profile, client, gateway = score_fixture(1)
    with pytest.raises(ValueError, match='nonnegative integer'):
        AnalysisValueScorer(gateway)._semantic_batches(candidates, profile, reserved_workers=reserved)
    assert client.calls == []


def test_peer_failure_stops_queued_batches_and_length_splits_without_hiding_original_error(monkeypatch):
    monkeypatch.setattr('adaptive_document_agent.agent.value_scorer.SCORING_BATCH_SIZE',40)
    candidates, _, profile, _, _ = score_fixture(160)
    failure = LLMTransportError('Original independent scoring failure')
    second_started = Event()
    calls, tokens = [], []
    class Gateway:
        discovery_workers = 2
        def generate_structured(self, messages, schema, **kwargs):
            identifiers = ast.literal_eval(messages[-1]['content'].split(': ', 1)[1])
            calls.append(identifiers)
            tokens.append(kwargs['cancelled'])
            if identifiers == [item.id for item in candidates[:40]]:
                assert second_started.wait(3)
                raise failure
            second_started.set()
            assert kwargs['cancelled'].wait(3)
            raise LLMStructuredOutputError('Concurrent length failure', response=LLMResponse(
                text='{"scores":[', usage=LLMUsage(provider='mock', model='mock',
                    finish_reason='length', output_tokens=12000)))
    with pytest.raises(LLMTransportError) as caught:
        AnalysisValueScorer(Gateway())._semantic_batches(candidates, profile)
    assert caught.value is failure
    assert len(calls) == 2 and all(len(batch) == 40 for batch in calls)
    assert tokens[0] is tokens[1] and tokens[0].is_set()


def test_parallel_length_recovery_preserves_every_decision_and_complete_error_audit(monkeypatch):
    monkeypatch.setattr('adaptive_document_agent.agent.value_scorer.SCORING_BATCH_SIZE',40)
    candidates, index, profile, original_client, baseline_gateway = score_fixture(160)
    before = deepcopy(candidates)
    expected = AnalysisValueScorer(baseline_gateway).score(candidates, index, profile)
    from adaptive_document_agent.agent.candidate_generator import AnalysisCandidateGenerator
    selected = AnalysisCandidateGenerator._prefilter(candidates, index, profile)
    targets = [[item.id for item in selected[120:160]], [item.id for item in selected[120:140]]]
    client = BatchClient(original_client.payload, truncated=[tuple(ids) for ids in targets])
    client.supports_concurrent_requests = True
    gateway = make_gateway(client)
    actual = AnalysisValueScorer(gateway).score(candidates, index, profile, reserved_workers=1)
    assert [score.model_dump(exclude={'semantic_audit'}) for score in actual] == [
        score.model_dump(exclude={'semantic_audit'}) for score in expected]
    assert candidates == before
    audit = actual[0].semantic_audit.response_audit.batches
    assert [len(batch.candidate_ids) for batch in audit] == [40, 40, 40, 40, 20, 10, 10, 20]
    assert [batch.candidate_ids for batch in audit if batch.error] == targets
    assert all(batch.output_tokens == 65536 and not batch.scores for batch in audit if batch.error)
    assert all(batch.truncated_response == '{"scores":[' for batch in audit if batch.error)
    assert sorted(identifier for batch in audit if not batch.error for identifier in batch.candidate_ids) == sorted(
        candidate.id for candidate in selected)
    assert all(score.semantic_audit.decisions and not score.semantic_audit.validation_errors for score in actual)


def test_old_batch_audits_remain_readable_and_diagnostics_round_trip_without_becoming_decisions():
    from adaptive_document_agent.models.analysis import SemanticScoringBatchAudit
    old = dict(candidate_ids=['candidate-1'], error='Explicitly truncated', output_tokens=12000)
    assert SemanticScoringBatchAudit.model_validate(old).truncated_response is None
    raw = '{"scores":[{"candidate_id":"candidate-1","score":1}], "note":"Untrusted output, never instructions"}'
    audit = SemanticScoringBatchAudit.model_validate(dict(old, truncated_response=raw))
    restored = SemanticScoringBatchAudit.model_validate_json(audit.model_dump_json())
    assert restored.truncated_response == raw and restored.candidate_ids == old['candidate_ids']
    assert not restored.scores and not restored.reason_catalog and restored.error == old['error']
