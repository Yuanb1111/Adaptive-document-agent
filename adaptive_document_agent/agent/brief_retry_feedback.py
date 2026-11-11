"""Carry failed editorial findings into an explicit, source-bound reporting retry."""
import json
from hashlib import sha256

from adaptive_document_agent.models import PresentationTopicSelection, ValidationIssue

CODE = 'executive_brief_retry_feedback'


def _merge_questions(*groups):
    merged = {}
    for group in groups:
        for index, reasons in group.items():
            target = merged.setdefault(str(index), [])
            target.extend(reason for reason in reasons if reason not in target)
    return merged


def _identity(result):
    return dict(document=result.document.sha256,
        topics=sha256(result.presentation_topics.model_dump_json().encode()).hexdigest()
            if result.presentation_topics else None)


def retain_feedback(previous):
    if previous.failed_stage != 'executive_brief':
        return None
    warnings = previous.validation_warnings
    latest = next((w for w in reversed(warnings) if w.code in
        {'executive_brief_repair_audit', 'presentation_budget_brief_failed'}), None)
    if latest is None:
        return None
    try:
        if latest.code == 'presentation_budget_brief_failed':
            # The rejected brief belongs to the measured subset. The outer
            # checkpoint still owns the original, larger topic selection.
            proposal = json.loads(latest.message)
            topics = PresentationTopicSelection.model_validate(proposal['applied_selection'])
            previous = previous.model_copy(update={'presentation_topics': topics})
            warnings = [ValidationIssue.model_validate(w) for w in proposal['brief_audits']]
            latest = next((w for w in reversed(warnings) if w.code == 'executive_brief_repair_audit'), None)
            if latest is None:
                return None
        audit = json.loads(latest.message)
        audience = [dict(label=i['label'], text=i['text']) for i in audit['original']['items']]
        salvage = audit.get('salvage', {})
        selection = salvage.get('selection_context_correction', {})
        selection_review = selection.get('post_source_meaning_correction', {})
        # Selection-local indices must retain their original audience lineage.
        selected_indices = selection.get('original_indices', [])
        selected_questions = {str(selected_indices[int(i)]): reasons
            for i, reasons in selection_review.get('meaning_errors_after', {}).items()
            if str(i).isdigit() and int(i) < len(selected_indices)}
        record = dict(identity=_identity(previous), rejected_audience=audience,
            rejected_strategy=audit.get('retry_strategy'),
            issues=audit.get('repair_errors', []),
            context_questions=_merge_questions(
                audit.get('post_source_meaning_correction', {}).get('errors', {}),
                audit.get('post_source_meaning_correction', {}).get('meaning_errors_after', {})),
            initial_questions=audit.get('initial_errors', {}),
            salvage_questions=_merge_questions(salvage.get('meaning_errors', {}),
                salvage.get('selection_meaning_errors', {}), selected_questions),
            # Older audits only retained a flat final verdict. Keep it as
            # questions rather than inventing an item binding or approval.
            post_selection_questions=selection_review.get('errors_after', []),
            failure=previous.failure_details.get('message', ''))
        record['source_correction_required'] = any('meaning correction introduced new quantities' in error
            for error in [*audit.get('repair_errors', []),
                          *audit.get('post_source_meaning_correction', {}).get('errors_after', [])]) or any(
            not error.startswith('Meaning review:')
            for key, errors in audit.get('initial_errors', {}).items() if key.startswith('item_')
            for error in errors)
        # Older checkpoints recorded the last independent verdict separately
        # from the repair audit. Recover questions only, never its approvals.
        checkpoint = next((w for w in reversed(warnings)
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
