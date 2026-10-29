"""Exact-context review checkpoints, separate from source or semantic rejection."""
import hashlib
import json

from adaptive_document_agent.models import ValidationIssue


class BriefReviewUnavailable(RuntimeError):
    """No semantic verdict: bypass copy repair until the writer boundary."""

    def __init__(self, failures):
        self.failures = failures
        super().__init__('Brief meaning review incomplete: ' + '; '.join(
            f'item {index + 1}: {reason}' for index, reason in sorted(failures.items()))
            + '. Completed item checks retained; retry reporting for unfinished checks.')


def context_key(brief, source_context, result):
    # Reuse requires unchanged whole-brief context, source values, evidence and
    # assurance decisions, not merely an unchanged sentence or item number.
    values = dict(contract='brief-review-checkpoint-v2', brief=brief.model_dump(mode='json') if brief is not None else None,
                  source_context=source_context)
    if result is not None:
        for field in ('document', 'profile', 'observations', 'analysis_results', 'presentation_topics',
                      'presentation_plan', 'insights'):
            value = getattr(result, field)
            values[field] = ([v.model_dump(mode='json') for v in value] if isinstance(value, list)
                             else value.model_dump(mode='json') if value is not None else None)
        values['assurance'] = [w.message for w in result.validation_warnings
                               if w.code == 'report_audit_scope_review']
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load_checks(result, key, count):
    if result is None:
        return {}
    for warning in reversed(result.validation_warnings):
        if warning.code != 'executive_brief_review_checkpoint':
            continue
        try:
            data = json.loads(warning.message)
            if data['context_key'] != key:
                continue
            # Persistence resumes interrupted work only. A fresh independent
            # review must not inherit approval from a completed prior review.
            if not data.get('pending'):
                return {}
            checks = data['checked']
            if not all(str(i).isdigit() and 0 <= int(i) < count
                       and isinstance(errors, list) and all(isinstance(e, str) for e in errors)
                       for i, errors in checks.items()):
                continue
            return {int(i): errors for i, errors in checks.items()}
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return {}


def save_checks(result, key, brief, checked, unavailable, source_context):
    if result is None:
        return
    record = dict(context_key=key, environment_key=context_key(None, None, result),
                  source_context=source_context, candidate=brief.model_dump(mode='json'), checked=checked,
                  unavailable=unavailable,
                  pending=[i for i in range(len(brief.items)) if i not in checked],
                  semantic_approval=not unavailable and len(checked) == len(brief.items)
                                    and not any(checked.values()))
    result.validation_warnings.append(ValidationIssue(code='executive_brief_review_checkpoint',
        stage='report', severity='warning' if unavailable else 'info',
        message=json.dumps(record, ensure_ascii=False)))
