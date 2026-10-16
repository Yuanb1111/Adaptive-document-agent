"""Offline response-capacity scenarios; no live latency or billing claims.

Run with ``python -m scripts.benchmark_candidate_capacity``. The real scorer and
gateway receive the same 160 synthetic candidates in every request. Only the
mock response-capacity rule and initial decision batch size vary. Complete raw
source fields, accepted/rejected decisions and expanded reasons must match.
"""
import ast
import hashlib
import json
from threading import Lock
from unittest.mock import patch


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _fixture():
    from adaptive_document_agent.document_model import DocumentIndex
    from adaptive_document_agent.models import AnalysisCandidate, DocumentProfile, Observation, SourceEvidence
    candidates, observations, decisions = [], [], []
    for index in range(160):
        metric = f'Measured queue duration {index}'
        identifiers = [f'observation-{index}-{year}' for year in (2023, 2024, 2025)]
        candidates.append(AnalysisCandidate(id=f'candidate-{index}', title=f'Compare {metric}',
            analysis_type='period_comparison', metric=metric, observation_ids=identifiers,
            reason='Compare complete reported periods while preserving source scope and units.'))
        for identifier, year, value in zip(identifiers, (2023, 2024, 2025), (100, 115, 130)):
            observations.append(Observation(id=identifier, metric_original=metric, value=value,
                raw_value=f'{value}.0', unit='minutes', period=str(year), confidence=.9,
                evidence=[SourceEvidence(page=1, text=f'{metric}: {value}.0 minutes in {year}',
                    extraction_method='synthetic_fixture', confidence=.9)]))
        qualification = (f'The qualification for candidate-{index} belongs only to this exact measured '
            'series and its complete reported periods. Preserve the source unit, comparable scope, '
            'measurement basis and limitations; do not turn association into an unsupported cause. ')
        decisions.append(dict(candidate_id=candidates[-1].id, score=.9 - .05*(index % 8),
            rejected=index % 7 == 0, reason_refs=['common'],
            reasons=[qualification * 8, 'Exact evidence membership: ' + ', '.join(identifiers)]))
    profile = DocumentProfile(document_purpose='Compare reported measurements',
                              metrics=[candidate.metric for candidate in candidates])
    payload = dict(reason_catalog=[dict(id='common', text='Judge usefulness across the complete supplied candidate set.')],
                   scores=decisions)
    return candidates, DocumentIndex(observations), profile, payload


def _measure(initial_batch_size, scenario):
    from adaptive_document_agent.agent import value_scorer
    from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
    from adaptive_document_agent.services.llm.base import LLMResponse
    from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
    from adaptive_document_agent.services.llm.usage import LLMUsage
    candidates, index, profile, payload = _fixture()
    selected = value_scorer.AnalysisCandidateGenerator._prefilter(candidates, index, profile)
    candidate_values = [candidate.model_dump(mode='json') for candidate in selected]
    source_before = _digest(dict(candidates=candidate_values,
        observations=[observation.model_dump(mode='json') for observation in index.observations]))
    last = [candidate.id for candidate in selected[-40:]]
    sparse_failures = {tuple(last), tuple(last[:20])}

    class CapacityClient(MockLLMClient):
        supports_concurrent_requests = True
        def __init__(self):
            super().__init__()
            self.requests, self.lock = [], Lock()

        def generate_structured(self, messages, response_model, **kwargs):
            ids = ast.literal_eval(messages[-1]['content'].split(': ', 1)[1])
            wire = ast.literal_eval(next(message['content'] for message in messages
                if message['content'].startswith('<UNTRUSTED_DOCUMENT_CONTENT>'))
                .split('\n', 1)[1].rsplit('\n', 1)[0])
            restored = []
            for row in wire['candidates']:
                row = {**wire.get('candidate_constants', {}), **row}
                if 'observation_refs' in row:
                    row['observation_ids'] = [wire['observation_id_catalog'][position]
                                             for position in row.pop('observation_refs')]
                if 'source_reason_ref' in row:
                    row['reason'] = wire['source_reason_catalog'][row.pop('source_reason_ref')]
                restored.append(row)
            assert restored == candidate_values, 'A request lost complete global candidate context'
            response = dict(reason_catalog=payload['reason_catalog'],
                            scores=[decision for decision in payload['scores'] if decision['candidate_id'] in ids])
            serialized = json.dumps(response, ensure_ascii=False)
            truncated = ((scenario == 'verbose_all_over_20' and len(ids) > 20)
                         or (scenario == 'sparse_last_parent_and_child' and tuple(ids) in sparse_failures))
            physical_text = serialized[:len(serialized)//2] if truncated else serialized
            with self.lock:
                self.requests.append(dict(candidate_ids=ids, truncated=truncated,
                    request_characters=len(json.dumps(messages, ensure_ascii=False))
                        + len(json.dumps(response_model.model_json_schema(), ensure_ascii=False)),
                    response_characters=len(physical_text)))
            response_record = LLMResponse(text=physical_text, usage=LLMUsage(provider='mock', model='capacity-fixture',
                finish_reason='length' if truncated else 'stop', output_tokens=12000 if truncated else None))
            if truncated:
                raise LLMStructuredOutputError('Mocked response-capacity failure', response=response_record)
            return response_model.model_validate(response), response_record

    client = CapacityClient()
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.DEEPSEEK, discovery_workers=4),
                         cache_enabled=False)
    with patch.object(value_scorer, 'SCORING_BATCH_SIZE', initial_batch_size):
        scores = value_scorer.AnalysisValueScorer(gateway).score(candidates, index, profile, reserved_workers=1)
    semantics = [dict(score=score.model_dump(mode='json', exclude={'semantic_audit'}),
        decisions=[decision.model_dump(mode='json') for decision in score.semantic_audit.decisions])
        for score in scores]
    source_after = _digest(dict(candidates=[candidate.model_dump(mode='json') for candidate in selected],
        observations=[observation.model_dump(mode='json') for observation in index.observations]))
    completed = [identifier for request in client.requests if not request['truncated']
                 for identifier in request['candidate_ids']]
    audit = scores[0].semantic_audit.response_audit.batches
    return dict(initial_decision_batch_size=initial_batch_size, scoring_worker_budget=3,
        candidate_count=len(selected), physical_attempts=len(client.requests),
        truncated_attempts=sum(request['truncated'] for request in client.requests),
        successful_attempts=sum(not request['truncated'] for request in client.requests),
        request_characters=sum(request['request_characters'] for request in client.requests),
        response_characters=sum(request['response_characters'] for request in client.requests),
        source_unchanged=source_before == source_after,
        every_candidate_completed_once=sorted(completed) == sorted(candidate.id for candidate in selected),
        every_decision_and_reason_valid=all(score.semantic_audit.decisions
            and not score.semantic_audit.validation_errors for score in scores),
        outcome_sha256=_digest(semantics),
        failure_audit_count=sum(bool(batch.error) for batch in audit),
        requests=sorted(client.requests, key=lambda request: tuple(request['candidate_ids'])))


def run():
    report = dict(mode='synthetic_offline_response_capacity',
        network_calls=0, provider_token_usage=None,
        request_character_definition='JSON-serialized messages plus the complete response JSON schema; not provider tokens or billing.',
        limitation='Mocked response-length verdicts model capacity, not provider latency or billing. '
            'The sparse case mirrors the reported failure shape, not fresh document semantics. '
            'No elapsed-time improvement is claimed. Smaller initial batches repeat complete global input more often.',
        scenarios={})
    for scenario in ('verbose_all_over_20', 'no_truncation', 'sparse_last_parent_and_child'):
        old, new = _measure(40, scenario), _measure(20, scenario)
        report['scenarios'][scenario] = dict(baseline_40=old, current_20=new,
            identical_outcomes=old['outcome_sha256'] == new['outcome_sha256'],
            physical_attempt_delta=new['physical_attempts']-old['physical_attempts'],
            request_character_delta=new['request_characters']-old['request_characters'])
    return report


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
