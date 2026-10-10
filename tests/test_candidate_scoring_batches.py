"""Truncated scoring recovers from original inputs without erasing decisions."""
import ast
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent import value_scorer
from adaptive_document_agent.agent.value_scorer import AnalysisValueScorer
from adaptive_document_agent.models import CandidateScore
from adaptive_document_agent.services.llm import LLMGateway,LLMSettings,MockLLMClient,ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError,PrivacyViolationError,LLMTransportError
from tests.test_candidate_scoring_compaction import scoring_fixture


class BatchClient(MockLLMClient):
    def __init__(self, payload, *, truncated=(), always_truncated=False, failure=None):
        super().__init__()
        self.payload=payload
        self.truncated=set(truncated)
        self.always_truncated=always_truncated
        self.failure=failure
        self.targets=[]

    def generate_structured(self,messages,response_model,**kwargs):
        self.calls.append(messages)
        ids=ast.literal_eval(messages[-1]['content'].split(': ',1)[1])
        self.targets.append(ids)
        if self.failure is not None:
            raise self.failure
        if self.always_truncated or tuple(ids) in self.truncated:
            raise LLMStructuredOutputError('Output limit',response=LLMResponse(text='{"scores":[',
                usage=LLMUsage(provider='mock',model='mock',finish_reason='length',output_tokens=65536)))
        response={'reason_catalog':self.payload.get('reason_catalog',[]),
                  'scores':[d for d in self.payload['scores'] if d['candidate_id'] in ids]}
        return response_model.model_validate(response),LLMResponse(text=json.dumps(response),
            usage=LLMUsage(provider='mock',model='mock',finish_reason='stop'))


def score_fixture(count=81,**kwargs):
    candidates,index,profile,payload,_=scoring_fixture(count)
    client=BatchClient(payload,**kwargs)
    gateway=LLMGateway(client,LLMSettings(provider=ProviderName.MOCK))
    return candidates,index,profile,client,gateway


def test_batched_scores_keep_global_ranking_full_context_and_original_source_fields(monkeypatch):
    candidates,index,profile,client,gateway=score_fixture()
    original=[c.model_dump() for c in candidates]
    batched=AnalysisValueScorer(gateway).score(candidates,index,profile,maximum=12)
    assert len(client.targets)==3 and max(map(len,client.targets))<=40
    assert sorted(i for batch in client.targets for i in batch)==sorted(c.id for c in candidates)
    for messages in client.calls:
        wire=ast.literal_eval(messages[1]['content'].split('\n',1)[1].rsplit('\n',1)[0])
        assert len(wire['candidates'])==81
    monkeypatch.setattr(value_scorer,'SCORING_BATCH_SIZE',160)
    other=BatchClient(client.payload)
    monolithic=AnalysisValueScorer(LLMGateway(other,LLMSettings(provider=ProviderName.MOCK))).score(candidates,index,profile,maximum=12)
    assert [s.model_dump(exclude={'semantic_audit'}) for s in batched]==[s.model_dump(exclude={'semantic_audit'}) for s in monolithic]
    assert [c.model_dump() for c in candidates]==original
    restored=CandidateScore.model_validate_json(batched[0].model_dump_json())
    assert restored==batched[0] and len(restored.semantic_audit.response_audit.batches)==3


def test_length_65536_failure_splits_only_failed_batch_and_keeps_completed_requests_cached(tmp_path):
    from adaptive_document_agent.utils.caching import DiskCache
    candidates,index,profile,client,gateway=score_fixture()
    bounded=value_scorer.AnalysisCandidateGenerator._prefilter(candidates,index,profile)
    failed=tuple(c.id for c in bounded[40:80])
    client.truncated.add(failed)
    gateway.cache=DiskCache(tmp_path)
    scores=AnalysisValueScorer(gateway).score(candidates,index,profile)
    assert list(map(len,client.targets))==[40,40,20,20,1]
    assert client.targets[2]+client.targets[3]==list(failed)
    audit=scores[0].semantic_audit.response_audit
    assert len(audit.batches)==5
    assert audit.batches[1].output_tokens==65536 and audit.batches[1].error
    assert not audit.batches[1].scores
    assert all(s.semantic_audit.decisions for s in scores)
    before=deepcopy(scores)
    repeat=AnalysisValueScorer(gateway).score(candidates,index,profile)
    assert repeat==before
    assert len(client.calls)==6  # Only the failed parent has no successful cache.


def test_reused_rationale_ids_stay_bound_to_their_original_batch(monkeypatch):
    candidates,index,profile,client,gateway=score_fixture(2)
    monkeypatch.setattr(value_scorer,'SCORING_BATCH_SIZE',1)
    payload=client.payload
    class CatalogClient(BatchClient):
        def generate_structured(self,messages,response_model,**kwargs):
            ids=ast.literal_eval(messages[-1]['content'].split(': ',1)[1])
            response=deepcopy(payload)
            response['reason_catalog']=[{'id':'r','text':'Qualification belonging only to '+ids[0]}]
            for decision in response['scores']:
                decision['reason_refs']=['r'];decision['reasons']=[]
            self.payload=response
            return super().generate_structured(messages,response_model,**kwargs)
    gateway.client=CatalogClient(payload)
    scores=AnalysisValueScorer(gateway).score(candidates,index,profile)
    for score in scores:
        assert 'Qualification belonging only to '+score.candidate.id in score.reasons
        assert score.semantic_audit.decisions[0].reason_refs==['r']
        assert not score.semantic_audit.validation_errors
    assert not scores[0].semantic_audit.response_audit.validation_errors


def test_context_only_decision_cannot_leak_into_another_batch(monkeypatch):
    candidates,index,profile,client,gateway=score_fixture(2)
    monkeypatch.setattr(value_scorer,'SCORING_BATCH_SIZE',1)
    class CrossBatch(BatchClient):
        def generate_structured(self,messages,response_model,**kwargs):
            self.calls.append(messages)
            response=deepcopy(self.payload) if len(self.calls)==1 else {'scores':[]}
            return response_model.model_validate(response),LLMResponse(text=json.dumps(response))
    gateway.client=CrossBatch(client.payload)
    scores=AnalysisValueScorer(gateway).score(candidates,index,profile)
    omitted=ast.literal_eval(gateway.client.calls[1][-1]['content'].split(': ',1)[1])[0]
    unreviewed=next(s for s in scores if s.candidate.id==omitted)
    assert unreviewed.rejected and not unreviewed.semantic_audit.decisions
    assert scores[0].semantic_audit.response_audit.unmatched_decisions


@pytest.mark.parametrize('failure',[PrivacyViolationError('Local only'),LLMTransportError('Unavailable')])
def test_privacy_and_transport_errors_do_not_trigger_smaller_batches(failure):
    candidates,index,profile,client,gateway=score_fixture(failure=failure)
    with pytest.raises(type(failure)):
        AnalysisValueScorer(gateway).score(candidates,index,profile)
    assert len(client.calls)==1


def test_repeated_truncation_has_bounded_retries_and_remains_a_visible_failure():
    candidates,index,profile,client,gateway=score_fixture(always_truncated=True)
    with pytest.raises(LLMStructuredOutputError,match='65536'):
        AnalysisValueScorer(gateway).score(candidates,index,profile)
    assert list(map(len,client.targets))==[40,20,10,5]
