"""Retain source-valid unfinished proposals for fresh independent review on retry."""
import json

from adaptive_document_agent.services.llm.structured import validate_structured_text
from .report_audit_batches import AUDIT_REQUEST_STRATEGY, BATCHED_AUDIT_CONTRACT, batch_context


def pending_audit_drafts(result, context):
    """Reuse only the latest unrejected proposal under an identical source scope.

    This never supplies approval. Complete schema failures are revalidated under
    the current schema; truncated outputs and superseded/rejected drafts are not
    candidates. The caller must perform a new independent model review.
    """
    from .report_audit_scope import AuditScopeDraft, _fingerprint, _validate
    latest = next((w for w in reversed(result.validation_warnings)
                   if w.code in {'report_audit_scope_review', 'report_audit_scope_unresolved'}), None)
    if latest is None or latest.code != 'report_audit_scope_unresolved':
        return {}
    try:
        audit = json.loads(latest.message)
        if (audit.get('contract') != BATCHED_AUDIT_CONTRACT
                or audit.get('request_strategy') != AUDIT_REQUEST_STRATEGY
                or audit.get('fingerprint') != _fingerprint(context)):
            return {}
        pending = {}
        for batch in audit['batches']:
            if batch.get('status') != 'failed' or not batch.get('attempts'):
                continue
            ids = batch['observation_ids']
            scoped = batch_context(context, ids)
            if batch.get('context_fingerprint') != _fingerprint(scoped):
                continue
            last = batch['attempts'][-1]
            # A substantive or malformed reviewer response must not be erased
            # by requesting a new opinion on the same rejected proposal.
            if 'review' in last or last.get('review_contract_corrections'):
                continue
            output = last.get('draft_output_attempts', [])
            if output and output[-1].get('status') not in {'response_received', 'invalid_format'}:
                continue
            try:
                if 'draft' in last:
                    draft = AuditScopeDraft.model_validate(last['draft'])
                    origin = 'unreviewed_draft'
                else:
                    raw = last.get('format_failure', {}).get('raw_response')
                    if not isinstance(raw, str):
                        continue
                    draft = validate_structured_text(raw, AuditScopeDraft)
                    origin = 'complete_schema_failure_revalidated'
                _validate(draft, scoped)
            except (ValueError, TypeError):
                continue
            key = tuple(ids)
            if key in pending:
                return {}  # Ambiguous checkpoint ownership cannot seed a review.
            pending[key] = dict(draft=draft.model_dump(mode='json'), origin=origin,
                source_context_fingerprint=batch['context_fingerprint'],
                source_attempt=len(batch['attempts']), semantic_approval=False)
        return pending
    except (ValueError, KeyError, TypeError, AttributeError):
        return {}
