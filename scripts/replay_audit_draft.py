"""Replay recorded malformed and invalid audit drafts; stop before fresh model output.

Usage: python scripts/replay_audit_draft.py path/to/analysis.json
Reads private diagnostics in place; prints only control flow and validation counts.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.report_audit_batches import batch_context
from adaptive_document_agent.agent.report_audit_scope import AuditScopeDraft, _review_batch
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.llm.structured import validate_structured_text


class FreshWriterRequired(RuntimeError):
    pass


class RecordedDraftSequence:
    def __init__(self, malformed, corrected_format):
        self.outputs = iter([malformed, json.dumps(corrected_format)])
        self.calls = 0
        self.source = None
        self.feedback = None

    def generate_structured(self, messages, schema, **kwargs):
        assert schema is AuditScopeDraft, 'Invalid recorded drafts must not reach review.'
        self.calls += 1
        if self.source is None:
            self.source = deepcopy(messages[1])
        assert messages[1] == self.source, 'Full source evidence changed during correction.'
        raw = next(self.outputs, None)
        if raw is None:
            self.feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert self.feedback['corrective_kind'] == 'binding_validation'
            assert self.feedback['validation_issues']
            raise FreshWriterRequired('Fresh writer correction and independent review are required.')
        try:
            return validate_structured_text(raw, schema)
        except ValueError as exc:
            raise LLMStructuredOutputError('Recorded response failed schema validation',
                response=LLMResponse(text=raw)) from exc


def replay(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(w['message'] for w in reversed(raw['validation_warnings'])
        if w['code'] == 'report_audit_scope_unresolved'))
    rows = []
    for number, batch in enumerate(audit['batches']):
        attempts = batch.get('attempts', [])
        for first, second in zip(attempts, attempts[1:]):
            malformed = first.get('format_failure', {}).get('raw_response')
            if malformed is None or 'draft' not in second or not second.get('validation_issues'):
                continue
            context = batch_context(audit['context'], batch['observation_ids'])
            original = deepcopy(context)
            gateway, record = RecordedDraftSequence(malformed, second['draft']), dict(attempts=[])
            try:
                _review_batch(gateway, context, record)
            except FreshWriterRequired:
                assert context == original and 'status' not in record
                contracts = gateway.feedback['target_contracts']
                rows.append(dict(batch=number, status='reached_fresh_binding_correction',
                    draft_requests=gateway.calls, recorded_responses=2,
                    corrections_used=record['corrections_used'],
                    delivered_validation_issues=len(gateway.feedback['validation_issues']),
                    unresolved_only_targets=sum(c['allowed_dispositions'] == ['unresolved'] for c in contracts),
                    source_unchanged=True, semantic_approval=False))
            else:
                raise AssertionError('Recorded invalid output must not become acceptance.')
            break
    if not rows:
        raise ValueError('No recorded schema failure followed by a binding failure was found.')
    return dict(recorded_pipeline_version=raw['pipeline_version'], batches=rows,
        model_calls=0, end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    print(json.dumps(replay(parser.parse_args().path), indent=2))
