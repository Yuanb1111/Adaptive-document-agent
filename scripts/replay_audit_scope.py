"""Recheck recorded audit batches offline; never manufacture missing model reviews.

Usage: python scripts/replay_audit_scope.py path/to/analysis.json
Reads private input in place and prints only validation counts and control-flow status.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaptive_document_agent.agent.report_audit_batches import batch_context, completed_batch
from adaptive_document_agent.agent.report_audit_scope import (
    AuditBindingValidationError, AuditScopeDraft, AuditScopeReview, _review_batch, _validate,
)


class IndependentReviewRequired(RuntimeError):
    pass


class RecordedDraftGateway:
    """Return the recorded draft; stop at the mandatory independent model boundary."""
    def __init__(self, draft):
        self.draft = draft

    def generate_structured(self, messages, schema, **kwargs):
        if schema is AuditScopeDraft:
            return self.draft.model_copy(deep=True)
        if schema is AuditScopeReview:
            raise IndependentReviewRequired('Fresh independent review required.')
        raise AssertionError(f'Unexpected model operation: {schema.__name__}')


def replay(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(row['message'] for row in reversed(raw['validation_warnings'])
        if row['code'] in {'report_audit_scope_unresolved', 'report_audit_scope_review'}))
    rows = []
    for number, batch in enumerate(audit['batches']):
        row = dict(batch=number, recorded_status=batch['status'])
        context = batch_context(audit['context'], batch['observation_ids'])
        attempts = [attempt for attempt in batch.get('attempts', []) if 'draft' in attempt]
        if not attempts:
            row.update(status='no_complete_recorded_draft', semantic_approval=False)
        elif batch['status'] == 'complete':
            completed_batch(audit['context'], batch)
            row.update(status='recorded_approval_revalidated', semantic_approval=True)
        else:
            final = attempts[-1]
            draft = AuditScopeDraft.model_validate(final['draft'])
            row['recorded_validation_issues'] = len(final.get('validation_issues', []))
            try:
                _validate(draft, context)
            except AuditBindingValidationError as exc:
                row.update(status='binding_validation_failed', validation_issues=len(exc.issues),
                    issue_fields=[issue['field'] for issue in exc.issues], semantic_approval=False)
            else:
                record = dict(attempts=[])
                try:
                    _review_batch(RecordedDraftGateway(draft), context, record)
                except IndependentReviewRequired:
                    row.update(status='reached_independent_review', validation_issues=0,
                        semantic_approval=False)
                else:
                    raise AssertionError('A replay must never synthesize an independent approval.')
        rows.append(row)
    return dict(pipeline_version=raw['pipeline_version'], batches=rows,
        model_calls=0, end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    print(json.dumps(replay(parser.parse_args().path), ensure_ascii=False, indent=2))
