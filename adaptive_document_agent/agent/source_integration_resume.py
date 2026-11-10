"""Preserve accepted source additions while retrying their rejected siblings."""
import json


def editable_rejected_sections(draft, verdicts, original_count):
    """A partial rejection is editable only within its own existing additions."""
    rejected = {sid for sid, verdict in verdicts.items() if not verdict.accepted}
    if not rejected or rejected == set(verdicts):
        return []
    owners = {d.section_id: {i for i in d.brief_item_indexes if i >= original_count}
              for d in draft.decisions}
    if any(not owners.get(sid) for sid in rejected):
        return []
    targets = set.union(*(owners[sid] for sid in rejected))
    if any(targets & ids for sid, ids in owners.items() if sid not in rejected):
        return []
    return sorted(rejected)


def rejected_addition_sections(previous, retained, checks, original_count):
    """Return edit scopes only after the caller matched and validated the draft.

    Saved verdicts freeze copy, never approve it. Every section still receives
    a fresh independent review after the targeted patch.
    """
    if previous is None or retained is None:
        return None
    from .source_integration_review import SourceIntegrationDraft, SourceIntegrationReview
    issue = next((w for w in reversed(previous.validation_warnings)
                  if w.code in {'source_integration_review', 'source_integration_unresolved'}), None)
    if issue is None or issue.code != 'source_integration_unresolved':
        return None
    try:
        attempts = json.loads(issue.message)['attempts']
        for entry in reversed(attempts):
            try:
                proposal = SourceIntegrationDraft.model_validate(entry.get('draft'))
                review = SourceIntegrationReview.model_validate(entry['review'])
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if proposal != retained:
                continue
            verdicts = {v.section_id: v for v in review.verdicts}
            if len(verdicts) != len(review.verdicts) or set(verdicts) != set(checks):
                return None
            sections = editable_rejected_sections(retained, verdicts, original_count)
            return (verdicts, sections) if sections else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return None
