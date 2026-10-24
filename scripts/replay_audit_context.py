"""Check saved audit request sizes without models, network, edits or approval.

Usage: python scripts/replay_audit_context.py path/to/analysis_data.json
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.report_audit_context_budget import require_audit_context_budget
from adaptive_document_agent.agent.report_audit_scope import _context
from adaptive_document_agent.agent.report_audit_source_index import discovery_input, MAX_DISCOVERY_INPUT_CHARS
from adaptive_document_agent.models import PipelineResult


def replay(path):
    result = PipelineResult.model_validate_json(Path(path).read_text(encoding='utf-8'))
    context = _context(result)
    report = dict(pipeline_version=result.pipeline_version, semantic_approval=False, export_verified=False)
    if context is None:
        return dict(**report, audit_targets_present=False)
    budget = require_audit_context_budget(context)
    payload, _ = discovery_input(result, context)
    return dict(**report, **budget, audit_targets_present=True,
                navigation_characters=len(json.dumps(payload, ensure_ascii=False)),
                navigation_limit=MAX_DISCOVERY_INPUT_CHARS,
                remaining_source_character_budget=payload['remaining_source_character_budget'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    print(json.dumps(replay(parser.parse_args().analysis_json), indent=2))
