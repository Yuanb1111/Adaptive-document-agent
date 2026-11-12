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
    values = dict(contract='brief-review-checkpoint-v8-assurance-comparison-scope', brief=brief.model_dump(mode='json') if brief is not None else None,
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


def checkpoint_context_matches(record, brief, result):
    """Recognize only exact inputs, allowing deterministic navigation bookkeeping.

    link_coverage runs after briefing and fills section observation/topic IDs.
    Those IDs are derived from the complete observations and plan already in
    the hash. They are not source findings, scope decisions or approval.
    """
    context = record['source_context']
    def matches(sample):
        return (context_key(None, None, sample) == record.get('environment_key')
                and context_key(brief, context, sample) == record.get('context_key'))
    if matches(result):
        return True
    if result is None or result.profile.source_coverage is None:
        return False
    from .source_coverage import link_coverage
    linked = result.profile.model_copy(deep=True)
    link_coverage(linked.source_coverage, result.observations, result.presentation_plan)
    # Do not normalize arbitrary foreign navigation IDs into a valid record.
    for current, expected in zip(result.profile.source_coverage.sections,
                                 linked.source_coverage.sections, strict=True):
        if (current.observation_ids not in ([], expected.observation_ids)
                or current.planned_topic_ids not in ([], expected.planned_topic_ids)):
            return False
    empty = result.profile.model_copy(deep=True)
    for section in empty.source_coverage.sections:
        section.observation_ids, section.planned_topic_ids = [], []
    return any(matches(result.model_copy(update={'profile': profile}))
               for profile in (empty, linked))


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


def retry_checkpoints(previous, *, limit=4):
    """Retain bounded draft lineage, not only a rejected truncated selection."""
    retained, seen = [], set()
    warnings = previous.validation_warnings
    latest = next((w for w in reversed(warnings) if w.code in {
        'presentation_budget_brief_failed', 'executive_brief_review_checkpoint'}), None)
    if latest is not None and latest.code == 'presentation_budget_brief_failed':
        try:
            warnings = [ValidationIssue.model_validate(entry)
                        for entry in json.loads(latest.message)['brief_audits']]
        except (ValueError, KeyError, TypeError):
            return []
    for warning in reversed(warnings):
        if warning.code != 'executive_brief_review_checkpoint':
            continue
        try:
            key = json.loads(warning.message)['context_key']
        except (ValueError, KeyError, TypeError):
            continue
        if key in seen:
            continue
        seen.add(key)
        retained.append(warning.model_copy(deep=True))
        if len(retained) == limit:
            break
    return list(reversed(retained))


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
