"""Inspect a saved selection up to its new semantic request; never call a model.

Usage: python scripts/replay_topic_evidence_review.py PATH_TO_ANALYSIS_JSON
The private input and full request remain local and are not rewritten.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.agent.topic_evidence_review import review_topic_evidence, unreviewed_topics
from adaptive_document_agent.models import PipelineResult, PresentationPlan, PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.presentation_evidence_alignment import align_redundant_slide_evidence


class RequestReached(Exception):
    pass


class OfflineGateway:
    def generate_structured(self, messages, response_model, **kwargs):
        payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        self.request = dict(schema=response_model.__name__,
            topic_count=len(payload.get('topics', [])),
            series_count=len(payload.get('series', payload.get('all_extracted_series', []))),
            context_characters=len(json.dumps(payload, ensure_ascii=False, separators=(',', ':'))),
            model_called=False, semantic_approval=False)
        raise RequestReached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json', type=Path)
    args = parser.parse_args()
    result = PipelineResult.model_validate_json(args.analysis_json.read_text(encoding='utf-8'))
    if not result.presentation_topics or not result.presentation_topics.topics:
        parser.error('Input has no saved selected topics.')
    original = hashlib.sha256(args.analysis_json.read_bytes()).hexdigest()
    _, lookup = series_directory(result)
    topics = result.presentation_topics.topics
    stale = sorted({sid for t in topics for sid in t.series_ids if sid not in lookup})
    excluded = [t.id for t in topics if set(t.series_ids) & set(stale)]
    slides = [PresentationSlide(id=t.id, slide_type='analysis', title=t.title,
        message=t.takeaway or t.question,
        observation_ids=[o.id for sid in t.series_ids for o in lookup[sid]]) for t in topics if t.id not in excluded]
    plan = PresentationPlan(title='Offline diagnostic', slides=slides)
    alignments = align_redundant_slide_evidence(plan, result.observations, [])
    issues = ClaimValidator().validate_plan(plan, result.observations, [])
    pending = [t.id for t in topics] if stale else unreviewed_topics(result.presentation_topics, lookup, result)
    gateway = OfflineGateway()
    try:
        if stale:
            PresentationTopicSelector(gateway).select(result)
        else:
            review_topic_evidence(result.presentation_topics, lookup, result, gateway, PresentationTopicSelector._validate)
    except RequestReached:
        pass
    print(json.dumps(dict(pipeline_version=result.pipeline_version,
        topics=[dict(id=t.id, title=t.title, selected_metrics=sorted({o.metric_original
                    for sid in t.series_ids for o in lookup.get(sid, [])})) for t in topics],
        stale_series_ids=stale, direction_check_excluded_topics=excluded,
        exact_source_alignments=alignments,
        directional_issues=[dict(code=i.code, message=i.message) for i in issues],
        pending_semantic_review=pending, request=getattr(gateway, 'request', None),
        source_file_unchanged=original == hashlib.sha256(args.analysis_json.read_bytes()).hexdigest()),
        ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
