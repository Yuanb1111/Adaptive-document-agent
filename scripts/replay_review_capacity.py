"""Offline transport/context regression on saved analyses; no semantic certification.

Usage: python scripts/replay_review_capacity.py ANALYSIS_JSON [ANALYSIS_JSON ...]
Reads private inputs locally, injects length failures, and never writes a result,
calls an external model, or claims the retained topics passed semantic review.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.brief_companion_context import companion_excerpts
from adaptive_document_agent.agent.insight_source_context import build_source_contexts
from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.agent.topic_evidence_review import evidence_payload, MAX_CONTEXT
from adaptive_document_agent.agent.topic_review_output import review_batches, review_request
from adaptive_document_agent.models import PipelineResult, PresentationTopicSelection
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.llm.usage import LLMUsage
from adaptive_document_agent.services.topic_review_status import topic_review_gaps


class TransportReceipt(BaseModel):
    topic_ids: list[str]


class InjectedTransport:
    def __init__(self):
        self.messages = []

    def generate_structured(self, messages, schema, **kwargs):
        self.messages.append(messages)
        if len(self.messages) % 2:
            raise LLMStructuredOutputError('Injected offline length failure', response=LLMResponse(
                text='{', usage=LLMUsage(provider='mock', model='mock', finish_reason='length')))
        assert messages == self.messages[-2], 'A capacity retry changed the source context.'
        payload = json.loads(messages[-1]['content'])
        return schema(topic_ids=[t['id'] for t in payload['topics']])


def replay(path):
    original = path.read_bytes()
    result = PipelineResult.model_validate_json(original)
    selection = result.presentation_topics
    if not selection or not selection.topics:
        for issue in reversed(result.validation_warnings):
            if issue.code == 'presentation_topic_evidence_review':
                saved = json.loads(issue.message).get('original_topics')
                if saved:
                    selection = PresentationTopicSelection(topics=saved)
                    break
    _, lookup = series_directory(result)
    topics = selection.topics if selection else []
    stale = [t.id for t in topics if any(sid not in lookup for sid in t.series_ids)]
    gateway, audit, budget, failures = InjectedTransport(), {}, {'calls': 0}, []

    def request(batch):
        payload = evidence_payload(batch, lookup)
        # Every supplied series still contains all its exact original points.
        assert all(len(row['observations']) == len(lookup[row['series_id']]) for row in payload['series'])
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        record = {'topic_count': len(batch), 'source_chars': len(encoded)}
        audit.setdefault('batches', []).append(record)
        receipt = review_request(gateway, [dict(role='user', content=encoded)],
                                 TransportReceipt, record, budget)
        assert receipt.topic_ids == [t.id for t in batch]
        return dict.fromkeys(receipt.topic_ids, 'transport_only')

    completed = review_batches([t for t in topics if t.id not in stale],
        payload=lambda batch: evidence_payload(batch, lookup), request=request,
        characters=MAX_CONTEXT, record=audit,
        on_failure=lambda batch, reason: failures.append(dict(topic_ids=[t.id for t in batch], reason=reason)))
    valid = [r for r in result.analysis_results if r.result is not None and r.evidence]
    contexts = build_source_contexts(valid, result.observations, result.document,
                                   max_total_chars=max(36000, len(valid) * 6000))
    anchors = {q.page for i in (result.executive_brief.items if result.executive_brief else []) for q in i.evidence}
    excerpts = {p.page_number: p.text[:9000] for p in result.document.pages if p.page_number in anchors}
    assert original == path.read_bytes(), 'The private source file changed.'
    return dict(file=path.name, document_sha256=result.document.sha256,
        source_sha256=sha256(original).hexdigest(), source_unchanged=True,
        external_model_called=False, semantic_certification=False,
        topics=len(topics), stale_topics=stale, transport_recovered_topics=len(completed),
        physical_calls=budget['calls'], batches=audit.get('batches', []), failures=failures,
        visible_unverified_topics=[g['title'] for g in topic_review_gaps(result)],
        context_results=len(contexts), context_characters=[sum(len(p.text) for p in c) for c in contexts.values()],
        companion_pages=list(companion_excerpts(result, excerpts)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analyses', type=Path, nargs='+')
    print(json.dumps([replay(path) for path in parser.parse_args().analyses], ensure_ascii=False, indent=2))
