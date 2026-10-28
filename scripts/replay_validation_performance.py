"""Offline CPU replay from a saved report checkpoint, not an end-to-end SLA.

Run: python -m scripts.replay_validation_performance analysis.json [--profile]
Reconstructs source excerpts and planning drafts from saved audit records.
Replays recorded takeaway responses, uses no optional visual suggestions, and
blocks socket connections. It neither calls a model nor exports/approves a deck.
"""
import argparse
from contextlib import nullcontext
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
from time import perf_counter
from unittest.mock import patch

from adaptive_document_agent.models import PipelineResult


def replay_plan(result):
    from adaptive_document_agent.agent.presentation_planner import PresentationPlanner

    # Orchestrator compiles drafts before the final pipeline version is stamped.
    result.pipeline_version = PipelineResult.model_fields['pipeline_version'].default
    repairs, originals = [], {}
    for warning in result.validation_warnings:
        if warning.code == 'presentation_topic_takeaway_repair':
            record = json.loads(warning.message)
            repairs.append(record)
            originals.setdefault(warning.related_ids[0], record)
    for topic in result.presentation_topics.topics:
        if topic.id in originals:
            topic.title = originals[topic.id]['original_title']
            topic.takeaway = originals[topic.id]['original_takeaway']
    result.validation_warnings = [w for w in result.validation_warnings
        if not w.code.startswith(('executive_brief', 'report_audit_scope', 'analysis_time_limit'))
        and w.code != 'presentation_topic_takeaway_repair']

    class Recorded:
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'VisualSelection':
                return schema(suggestions=[])
            if schema.__name__ != 'TakeawayCorrection' or not repairs:
                raise AssertionError(f'Unrecorded model response required: {schema.__name__}')
            response = repairs.pop(0)
            return schema(title=response['proposed_title'], takeaway=response['proposed_takeaway'])

    plan = PresentationPlanner(Recorded()).plan(result)
    assert not repairs, 'All recorded correction responses must be consumed'
    return plan


def replay(path, *, profile=False):
    from adaptive_document_agent.agent.brief_native_transport import source_quantity_options
    try:
        from adaptive_document_agent.services.validation_cache import validation_cache_scope as scope
    except ModuleNotFoundError:  # Allows the same script to measure the baseline revision.
        scope = nullcontext

    result = PipelineResult.model_validate_json(Path(path).read_text(encoding='utf-8-sig'))
    checkpoint = json.loads(next(w.message for w in result.validation_warnings
                                 if w.code == 'executive_brief_review_checkpoint'))
    blocks = checkpoint['source_context']['evidence_blocks']
    excerpts = {}
    for block in blocks.values():
        excerpts[block['page']] = excerpts.get(block['page'], '') + '\n' + block['text']
    measurements = []
    for name, operation in [('source_options', lambda sample: source_quantity_options(sample, excerpts, blocks)),
                            ('planning_replay', replay_plan)]:
        sample = result.model_copy(deep=True)
        profiler = cProfile.Profile()
        started = perf_counter()
        with (scope(), patch('socket.socket.connect', side_effect=AssertionError('Offline replay')),
              patch('socket.socket.connect_ex', side_effect=AssertionError('Offline replay'))):
            output = profiler.runcall(operation, sample) if profile else operation(sample)
        elapsed = perf_counter() - started
        data = output.model_dump(mode='json') if hasattr(output, 'model_dump') else output
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        measurements.append(dict(operation=name, seconds=round(elapsed, 3), sha256=digest))
        if profile:
            pstats.Stats(profiler).sort_stats('cumulative').print_stats(20)
    return dict(measurements=measurements, model_calls=0, end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    print(json.dumps(replay(args.analysis_json, profile=args.profile), indent=2))
