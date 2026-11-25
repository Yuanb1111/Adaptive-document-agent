"""Preserve accepted source additions while retrying their rejected siblings."""
import json


def rejected_matching_proposal(previous, retained):
    """Old objections do not invalidate a newer, still-unreviewed valid proposal."""
    if previous is None or retained is None:
        return False
    from .source_integration_review import SourceIntegrationDraft, SourceIntegrationReview
    issue = next((w for w in reversed(previous.validation_warnings)
                  if w.code in {'source_integration_review', 'source_integration_unresolved'}), None)
    if issue is None:
        return False
    try:
        for entry in reversed(json.loads(issue.message)['attempts']):
            try:
                draft = SourceIntegrationDraft.model_validate(entry.get('draft'))
                review = SourceIntegrationReview.model_validate(entry.get('review'))
            except (ValueError, TypeError, AttributeError):
                continue
            if draft == retained:
                return any(not verdict.accepted for verdict in review.verdicts)
    except (ValueError, KeyError, TypeError):
        pass
    return False


def editable_rejected_sections(draft, verdicts, original_count, *, allow_full_capacity=False):
    """A partial rejection is editable only within its own existing additions."""
    rejected = {sid for sid, verdict in verdicts.items() if not verdict.accepted}
    if not rejected:
        return []
    if rejected == set(verdicts) and (
            not allow_full_capacity or len(draft.additions) < min(4, 7 - original_count)
            or any(d.disposition != 'include' for d in draft.decisions)):
        return []  # Unused capacity or omitted sections still need full planning.
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
            sections = editable_rejected_sections(retained, verdicts, original_count, allow_full_capacity=True)
            return (verdicts, sections, attempts, entry) if sections else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def retry_unreviewed_source_table(scoped_retry, retained, messages, pages, result, brief, checks):
    """Rebind a stopped writer's complete original table if only its old locator format failed."""
    from adaptive_document_agent.models.executive_brief import ExecutiveBriefItem
    from adaptive_document_agent.services.llm.structured import unique_json_object
    from .source_integration_copy import scoped_copy_sources
    from .source_integration_quotes import bind_source_quotes
    from .source_integration_review import SourceIntegrationDraft, _validate
    from .source_table_cells import source_cell_item_schema

    _, sections, attempts, entry = scoped_retry
    original_count = len(brief.items)
    targets = {i for d in retained.decisions if d.section_id in sections
               for i in d.brief_item_indexes if i >= original_count}
    try:
        failure = entry['targeted_format_failure']
        output = entry['copy_output_attempts'][-1]
        if (entry is not attempts[-1] or output['status'] != 'invalid_format'
                or output['usage']['finish_reason'] != 'stop' or output['raw_response'] != failure['raw_response']):
            return None
        errors = failure['schema_errors']
        if (not errors or any(e['type'] != 'literal_error' or len(e['loc']) != 5
                or e['loc'][1:3] != ['comparison_table', 'rows']
                or any(type(n) is not int or n < 0 for n in e['loc'][3:]) for e in errors)
                or {e['loc'][0] for e in errors} != {f'item_{i}' for i in targets}):
            return None
        writer = json.loads(output['raw_response'], object_pairs_hook=unique_json_object)
        if set(writer) != {f'item_{i}' for i in entry['edited_addition_indexes']}:
            return None
        submitted = SourceIntegrationDraft.model_validate(entry['submitted_draft'])
        if bind_source_quotes(submitted, pages, selected_phrase_evidence=True) != retained:
            return None
        for index in entry['edited_addition_indexes']:
            if not original_count <= index < original_count + len(submitted.additions):
                return None
            item = submitted.additions[index - original_count]
            raw = writer[f'item_{index}']
            if index not in targets:
                if ExecutiveBriefItem.model_validate(raw) != item:
                    return None
                continue
            owners = [d.section_id for d in retained.decisions if index in d.brief_item_indexes]
            schema = source_cell_item_schema(scoped_copy_sources(messages, owners))
            if schema is ExecutiveBriefItem:  # No source reference directory available.
                return None
            original = schema.model_validate(raw)
            if (original.comparison_table is None or item.comparison_table is None
                    or original.model_dump(exclude={'comparison_table'}) != item.model_dump(exclude={'comparison_table'})):
                return None
            item.comparison_table = original.comparison_table
        candidate = bind_source_quotes(submitted, pages, selected_phrase_evidence=True)
        if candidate == retained:
            return None
        for attempt in attempts:
            rejected = {v['section_id'] for v in attempt.get('review', {}).get('verdicts', []) if not v['accepted']}
            if rejected.intersection(sections):
                old = SourceIntegrationDraft.model_validate(attempt['draft'])
                for decision in old.decisions:
                    if decision.section_id in rejected and decision.section_id in sections:
                        for i in targets.intersection(decision.brief_item_indexes):
                            offset = i - original_count
                            if old.additions[offset].comparison_table == candidate.additions[offset].comparison_table:
                                return None
        _validate(candidate, result, brief, checks)
        return candidate
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        # Malformed, incomplete or stale archives use the ordinary scoped writer.
        return None
