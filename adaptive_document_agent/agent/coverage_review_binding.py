"""Bind completed semantic decisions to retained facts and later budget review."""
import json
from hashlib import sha256


def source_fingerprint(lookup):
    payload = {sid: [o.model_dump(mode='json') for o in items] for sid, items in lookup.items()}
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def selection_ids(selection):
    return {sid for topic in selection.get('topics', []) for sid in topic['series_ids']}


def completed_review_is_current(result, audit, lookup):
    """Budget changes require their own accepted, complete omission ledger."""
    if audit['source_fingerprint'] != source_fingerprint(lookup):
        return False
    reviewed = audit['review']
    original = selection_ids(reviewed)
    current = {sid for topic in (result.presentation_topics.topics if result.presentation_topics else [])
               for sid in topic.series_ids}
    if current == original:
        return True
    latest = next((w for w in reversed(result.validation_warnings)
        if w.code in {'presentation_physical_budget_review', 'presentation_physical_budget_failed'}), None)
    if latest is None or latest.code != 'presentation_physical_budget_review':
        return False
    try:
        budget = json.loads(latest.message)
        accepted = budget['attempts'][-1]
        decisions = accepted['review_target']['decisions']
        return (selection_ids(budget['original_selection']) == original
            and selection_ids(accepted['applied_selection']) == current
            and accepted['status'] == 'accepted'
            and accepted['independent_review']['accepted'] is True
            and len(decisions) == len(original)
            and {d['series_id'] for d in decisions} == original
            and {d['series_id'] for d in decisions if d['include']} == current
            and all(d['reason'].strip() for d in decisions))
    except (ValueError, KeyError, TypeError):
        return False
