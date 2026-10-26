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


class WriterCorrectionRequired(RuntimeError):
    pass


class RecordedReviewGateway:
    """Replay real reviewer responses; do not invent the missing corrected draft."""
    def __init__(self, attempt):
        self.attempt = attempt
        self.reviews = iter([item['review'] for item in attempt.get('review_contract_corrections', [])]
                            + [attempt['review']])
        self.calls = []
        self.source_message = None

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if self.source_message is None:
            self.source_message = messages[1]
        assert messages[1] == self.source_message, 'Full source context changed during correction.'
        if schema is AuditScopeDraft:
            if len(self.calls) == 1:
                return schema.model_validate(self.attempt['draft'])
            feedback = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert feedback['independent_review'] == self.attempt['review']
            assert feedback['corrective_kind'] == 'independent_review'
            raise WriterCorrectionRequired('Real rejection reached writer; fresh model output required.')
        assert schema is AuditScopeReview
        return schema.model_validate(next(self.reviews))


def replay_review_correction(context, attempt):
    gateway, record = RecordedReviewGateway(attempt), dict(attempts=[])
    try:
        _review_batch(gateway, context, record)
    except WriterCorrectionRequired:
        return dict(status='reached_writer_correction', operations=gateway.calls,
            corrections_used=record['corrections_used'], full_feedback_delivered=True,
            semantic_approval=False)
    raise AssertionError('Expected recorded reviewer rejection to reach a fresh writer correction.')


def replay_review_correction_path(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(row['message'] for row in reversed(raw['validation_warnings'])
        if row['code'] == 'report_audit_scope_unresolved'))
    rows = []
    for number, batch in enumerate(audit['batches']):
        if batch['status'] != 'failed':
            continue
        for attempt in batch.get('attempts', []):
            if (attempt.get('review_contract_corrections') and attempt.get('review')
                    and attempt['review']['unresolved_accepted'] is False):
                result = replay_review_correction(batch_context(audit['context'], batch['observation_ids']), attempt)
                rows.append(dict(batch=number, **result))
                break
    return dict(pipeline_version=raw['pipeline_version'], batches=rows,
        model_calls=0, end_to_end_verified=False)


def replay_review_schema_path(path):
    """Revalidate recorded complete output, preserving its full semantic verdict."""
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    audit = json.loads(next(row['message'] for row in reversed(raw['validation_warnings'])
        if row['code'] == 'report_audit_scope_unresolved'))
    rows, completed = [], 0
    for number, batch in enumerate(audit['batches']):
        if batch['status'] == 'complete':
            completed_batch(audit['context'], batch)
            completed += 1
            continue
        for attempt in batch.get('attempts', []):
            responses = [failure['raw_response'] for failure in attempt.get('review_contract_corrections', [])
                         if 'raw_response' in failure]
            if not responses:
                continue
            from adaptive_document_agent.services.llm.structured import validate_structured_text
            reviews = [validate_structured_text(value, AuditScopeReview) for value in responses]
            first = reviews[0]
            if first.unresolved_accepted:
                raise ValueError('This replay expects an unknown-disposition rejection, not an approval.')
            record = dict(draft=attempt['draft'], review=first.model_dump(mode='json'),
                          review_contract_corrections=[])
            flow = replay_review_correction(batch_context(audit['context'], batch['observation_ids']), record)
            rows.append(dict(batch=number, recorded_response_characters=[len(v.unresolved_reason) for v in reviews],
                recorded_outputs_schema_valid=len(reviews), **flow))
            break
    return dict(pipeline_version=raw['pipeline_version'], completed_batches_revalidated=completed,
        batches=rows, model_calls=0, end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--review-correction-path', action='store_true',
        help='Replay recorded review format repair and rejection through the real writer-correction path.')
    mode.add_argument('--review-schema-path', action='store_true',
        help='Revalidate complete recorded review responses and replay their rejection without truncation.')
    args = parser.parse_args()
    action = (replay_review_schema_path if args.review_schema_path else
              replay_review_correction_path if args.review_correction_path else replay)
    print(json.dumps(action(args.path), ensure_ascii=False, indent=2))
