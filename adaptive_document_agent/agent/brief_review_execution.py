"""Validate and checkpoint each complete review without turning capacity into meaning."""
import json
from time import perf_counter

from adaptive_document_agent.models import ValidationIssue
from .brief_meaning_capacity import complete_meaning_output
from .brief_review_checkpoint import BriefReviewUnavailable, context_key, load_checks, save_checks
from .brief_review_progress import report_brief_progress
from .brief_review_validation import validate_meaning_response
from .prompting import untrusted_document_message


def execute_review(gateway, *, brief, pending, messages, catalogs, errors, checked,
                   memo_key, capacity, result, cancelled, source_context):
    from .brief_meaning_review import BriefMeaningReview
    key = context_key(brief, source_context, result)
    completed = load_checks(result, key, len(brief.items))
    # In-memory successes retain the same whole-brief memo semantics as before.
    completed.update({i: checked[memo_key(item)] for i, item in enumerate(brief.items)
                      if memo_key(item) in checked})
    for i, reasons in completed.items():
        checked[memo_key(brief.items[i])] = reasons
        if reasons:
            errors[i] = reasons
    blocked = capacity.setdefault('unavailable_contexts', {})
    if key in blocked:
        raise BriefReviewUnavailable(blocked[key])
    shared = next((row['available_report_context'] for row in pending
                   if 'available_report_context' in row), None)
    pending = [row for row in pending if row['index'] not in completed]
    if not pending:
        return errors
    if shared is not None:
        pending[0]['available_report_context'] = shared
    messages = [messages[0], untrusted_document_message(json.dumps(pending, ensure_ascii=False))]
    unavailable, record = {}, {}

    def complete(response, rows, request):
        ids = {row['index'] for row in rows}
        if len(response.items) != len(ids) or {v.index for v in response.items} != ids:
            raise ValueError('Brief meaning review must cover every exact supplied index')
        report_brief_progress('checking source bindings, arithmetic and direction for items '
                              + ', '.join(str(i + 1) for i in sorted(ids)))
        failures = validate_meaning_response(gateway, response, brief=brief, pending=rows,
            messages=request, catalogs={i: catalogs[i] for i in ids}, result=result, cancelled=cancelled)
        for i in ids:
            reasons = failures.get(i, [])
            completed[i] = reasons
            checked[memo_key(brief.items[i])] = reasons
            if reasons:
                errors[i] = reasons
        save_checks(result, key, brief, completed, unavailable, source_context)
        report_brief_progress(f'{len(completed)}/{len(brief.items)} item checks completed')

    started = perf_counter()
    initial_meaning = result.stage_details_ms.get('executive_brief_meaning_review', 0) if result is not None else 0
    initial_direction = result.stage_details_ms.get('executive_brief_direction_review', 0) if result is not None else 0
    try:
        complete_meaning_output(gateway, messages, BriefMeaningReview, pending, record,
            capacity, cancelled=cancelled, on_complete=complete)
    except BriefReviewUnavailable as exc:
        unavailable.update(exc.failures)
        blocked[key] = dict(unavailable)  # No repeated automatic recovery for this context.
        save_checks(result, key, brief, completed, unavailable, source_context)
        raise
    finally:
        if result is not None:
            details = result.stage_details_ms
            elapsed = round((perf_counter()-started)*1000)
            direction = details.get('executive_brief_direction_review', 0) - initial_direction
            # Include request time once; nested binding checks already ran
            # inside this wall clock. Keep blind direction timing separate.
            details['executive_brief_meaning_review'] = initial_meaning + max(0, elapsed - direction)
            details['executive_brief_review_wall'] = details.get('executive_brief_review_wall', 0) + elapsed
            result.validation_warnings.append(ValidationIssue(code='executive_brief_meaning_capacity_audit',
                stage='report', severity='warning' if unavailable else 'info',
                message=json.dumps(record, ensure_ascii=False)))
    return errors
