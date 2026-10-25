"""Replay saved audit scheduling locally, without source output or model responses.

Usage: python scripts/replay_audit_lifecycle.py path/to/analysis_data.json
The request probe stops at the gateway boundary; it never approves source meaning.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.report_audit_context_budget import require_audit_context_budget
from adaptive_document_agent.agent.report_audit_scope import (
    _context, _targets, refresh_report_audit_scope, require_report_audit_scope,
)
from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.models.presentation import PresentationTopicSelection
from adaptive_document_agent.services.llm.exceptions import LLMResponseError


class RecordedResponseUnavailable(LLMResponseError):
    """The offline replay has no recorded response for this request."""


class RequestProbe:
    """Record request metadata only; no provider, credentials or network exist."""

    def __init__(self):
        self.requests = []

    def generate_structured(self, messages, schema, **kwargs):
        self.requests.append(dict(schema=schema.__name__, stage=kwargs.get('stage'),
                                  max_tokens=kwargs.get('max_tokens')))
        raise RecordedResponseUnavailable('Offline replay stopped before model execution.')


def audit_qualified_count(topics):
    """Inspect scheduling keywords only; this is no semantic review of caveats."""
    return sum(any(re.search(r'\b(?:audit(?:ed)?|unaudited)\b', note, re.I)
                   for note in topic.caveats) for topic in topics)


def replay(path):
    path = Path(path)
    saved = path.read_bytes()
    result = PipelineResult.model_validate_json(saved)
    budget_review = next((json.loads(issue.message) for issue in reversed(result.validation_warnings)
                         if issue.code == 'presentation_physical_budget_review'), None)
    if budget_review is None:
        raise ValueError('The export has no accepted physical-budget review to replay.')
    original = PresentationTopicSelection.model_validate(budget_review['original_selection'])
    original_qualified = audit_qualified_count(original.topics)
    # No audit-qualified topics proves an empty scheduling scope. Otherwise
    # the saved selection alone does not establish all historical theme IDs.
    original_count = 0 if original_qualified == 0 else None
    final_ids = {observation.id for observation in _targets(result)}
    saved_gate_passed = True
    try:
        require_report_audit_scope(result)
    except ValueError:
        saved_gate_passed = False
    context = _context(result)
    budget = require_audit_context_budget(context) if context else None
    probe = RequestProbe()
    candidate = result.model_copy(deep=True)
    stopped_before_model = False
    try:
        refresh_report_audit_scope(probe, candidate)
    except RecordedResponseUnavailable:
        stopped_before_model = True
    unchanged = path.read_bytes() == saved
    if not unchanged:
        raise RuntimeError('The input file changed during the read-only replay.')
    return dict(
        saved_version=result.pipeline_version,
        saved_failed_stage=result.failed_stage,
        original_scope_basis='saved_topic_caveats_only; original plan not reconstructed',
        original_audit_qualified_topic_count=original_qualified,
        final_audit_qualified_theme_count=audit_qualified_count(result.presentation_plan.themes),
        original_target_count=original_count, final_target_count=len(final_ids),
        introduced_target_count=len(final_ids) if original_count == 0 else None,
        saved_review_count=sum(issue.code == 'report_audit_scope_review'
                               for issue in result.validation_warnings),
        saved_unresolved_count=sum(issue.code == 'report_audit_scope_unresolved'
                                   for issue in result.validation_warnings),
        saved_audit_gate_passed=saved_gate_passed,
        context_budget=budget,
        refresh_requests=probe.requests,
        stopped_before_model=stopped_before_model,
        input_file_unchanged=unchanged,
        semantic_approval=False,
        export_verified=False,
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    print(json.dumps(replay(parser.parse_args().analysis_json), indent=2))
