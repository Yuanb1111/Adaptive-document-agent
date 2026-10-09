"""Resolve exact transport aliases without choosing a different evidence scope."""

import json
from collections import defaultdict

from adaptive_document_agent.models import ValidationIssue


def reference_aliases(lookup):
    aliases = defaultdict(set)
    for identifier in lookup:
        for prefix in ('presentation_series_', 'presentation_composition_'):
            if identifier.startswith(prefix):
                aliases[identifier[len(prefix):]].add(identifier)
    return {alias: next(iter(ids)) for alias, ids in aliases.items() if len(ids) == 1}


def bind_topic_references(selection, lookup, result=None):
    """Restore an omitted namespace only for a unique complete catalog suffix.

    Unknown IDs, partial hashes and ambiguous aliases remain invalid. Original
    references are audited; numeric, scope and claim validation still follows.
    """
    aliases, changes = reference_aliases(lookup), []

    def bind(identifier):
        target = identifier if identifier in lookup else aliases.get(identifier, identifier)
        if target != identifier:
            changes.append({'original': identifier, 'resolved': target})
        return target

    for topic in selection.topics:
        topic.series_ids = [bind(identifier) for identifier in topic.series_ids]
    for omission in selection.omissions:
        omission.series_id = bind(omission.series_id)
    for decision in getattr(selection, 'coverage_decisions', []):
        decision.series_id = bind(decision.series_id)
    if changes and result is not None:
        result.validation_warnings.append(ValidationIssue(
            code='presentation_reference_binding', stage='presentation', severity='info',
            message=json.dumps({'bindings': changes, 'basis': 'unique exact catalog suffix'}, ensure_ascii=False),
        ))
    return selection
