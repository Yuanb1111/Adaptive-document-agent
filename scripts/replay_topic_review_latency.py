"""Offline replay of saved verdicts; no model credentials or network requests.

Run with a saved analysis_data.json. Scaled delays exercise real scheduling;
they are not a measurement of a new provider response or end-to-end success.
"""
import argparse
from hashlib import sha256
import json
from time import perf_counter, sleep

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.agent.topic_evidence_review import review_topic_evidence
from adaptive_document_agent.models import PipelineResult, PresentationTopicSelection
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.base import LLMResponse


def replay(path, scale):
    original = PipelineResult.model_validate_json(path.read_text(encoding='utf-8'))
    audit = next(json.loads(w.message) for w in original.validation_warnings
                 if w.code == 'presentation_topic_evidence_review')
    drafts = PresentationTopicSelection(topics=audit['original_topics'])
    records = [a for a in audit['attempts'] if a['phase'] == 'independent_review']
    latencies = [u['latency_ms'] for u in original.llm_usage
                 if u.get('operation') == 'TopicEvidenceReview']
    saved = {tuple(d['topic_id'] for d in r['response']['decisions']): (r['response'], ms)
             for r, ms in zip(records, latencies)}
    if len(saved) != len(records):
        raise ValueError('Saved review/latency mapping is incomplete')

    class SavedClient(MockLLMClient):
        supports_concurrent_requests = True

        def generate_text(self, messages, **kwargs):
            payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            verdict, ms = saved[tuple(t['id'] for t in payload['topics'])]
            sleep(ms / 1000 * scale)
            return LLMResponse(text=json.dumps(verdict))

    measurements = []
    for workers in (1, 4):
        result = original.model_copy(deep=True)
        result.validation_warnings = [w for w in result.validation_warnings
                                     if w.code != 'presentation_topic_evidence_review']
        _, lookup = series_directory(result)
        gateway = LLMGateway(SavedClient(), LLMSettings(provider=ProviderName.DEEPSEEK,
                             model='offline-saved-verdicts', discovery_workers=workers))
        start = perf_counter()
        selected = review_topic_evidence(drafts, lookup, result, gateway,
                                         PresentationTopicSelector._validate, allow_correction=False)
        wall = perf_counter() - start
        projection = dict(selection=selected.model_dump(mode='json'),
                          audit=json.loads(result.validation_warnings[-1].message))
        digest = sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()
        measurements.append(dict(workers=workers, wall_seconds=round(wall, 4), digest=digest,
                                 calls=len(gateway.usage)))
    assert measurements[0]['digest'] == measurements[1]['digest']
    return dict(delay_scale=scale, measurements=measurements,
                observed_serial_provider_ms=sum(ms for _, ms in saved.values()),
                largest_saved_batch_ms=max(ms for _, ms in saved.values()),
                note='Saved verdicts and scaled delays; no live provider or complete-export performance claim.')


if __name__ == '__main__':
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--scale', type=float, default=.02)
    args = parser.parse_args()
    if not 0 < args.scale <= 1:
        parser.error('--scale must be greater than zero and at most one')
    print(json.dumps(replay(args.checkpoint, args.scale), indent=2))
