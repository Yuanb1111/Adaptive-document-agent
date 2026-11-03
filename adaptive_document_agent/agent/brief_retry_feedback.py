"""Carry failed editorial findings into an explicit, source-bound reporting retry."""
import json
from hashlib import sha256

from adaptive_document_agent.models import ValidationIssue

CODE = 'executive_brief_retry_feedback'


def _identity(result):
    return dict(document=result.document.sha256,
        topics=sha256(result.presentation_topics.model_dump_json().encode()).hexdigest()
            if result.presentation_topics else None)


def retain_feedback(previous):
    if previous.failed_stage != 'executive_brief':
        return None
    latest = next((w for w in reversed(previous.validation_warnings)
        if w.code == 'executive_brief_repair_audit'), None)
    if latest is None:
        return None
    try:
        audit = json.loads(latest.message)
        audience = [dict(label=i['label'], text=i['text']) for i in audit['original']['items']]
        record = dict(identity=_identity(previous), rejected_audience=audience,
            issues=audit.get('repair_errors', []),
            context_questions=audit.get('post_source_meaning_correction', {}).get('errors', {}),
            initial_questions=audit.get('initial_errors', {}),
            salvage_questions=(audit.get('salvage', {}).get('selection_meaning_errors')
                or audit.get('salvage', {}).get('meaning_errors', {})),
            failure=previous.failure_details.get('message', ''))
        # Older checkpoints recorded the last independent verdict separately
        # from the repair audit. Recover questions only, never its approvals.
        checkpoint = next((w for w in reversed(previous.validation_warnings)
            if w.code == 'executive_brief_review_checkpoint'), None)
        if not record['salvage_questions'] and checkpoint is not None:
            try:
                checked = json.loads(checkpoint.message).get('checked', {})
                record['salvage_questions'] = {k: v for k, v in checked.items() if v}
            except (ValueError, AttributeError):
                pass
        return ValidationIssue(code=CODE, stage='report', severity='info',
            message=json.dumps(record, ensure_ascii=False))
    except (ValueError, KeyError, TypeError):
        return None


def current_feedback(result):
    latest = next((w for w in reversed(result.validation_warnings) if w.code == CODE), None)
    if latest:
        try:
            record = json.loads(latest.message)
            if record['identity'] == _identity(result):
                return record
        except (ValueError, KeyError, TypeError):
            pass
    return None
