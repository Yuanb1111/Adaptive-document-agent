"""Bind audit qualifiers to explicit retained period metadata, never infer audit."""
import json
import re

from adaptive_document_agent.models import ValidationIssue

_PERIOD = re.compile(r'\b(?:FY\d{4}|\d{1,2}M\d{4}|\d{4}-\d{2}-\d{2})\b', re.I)


def _repair_clause(copy, observations):
    if not re.search(r'\bunaudited\b', copy, re.I):
        return copy
    claimed = {m.group().upper() for m in _PERIOD.finditer(copy)}
    if not claimed:
        return copy
    known = {str(o.period).rstrip('*').upper() for o in observations if o.audited_status == 'unaudited'}
    if claimed <= known:
        return copy
    # Unknown is not audited. Only restate the source's affirmative qualifier.
    return ('Source marks ' + ', '.join(sorted(known)) + ' as unaudited.' if known else
            'Audit status is not established for the periods in this statement.')


def _repair(copy, observations):
    # Unrelated limits remain visible even when a neighboring audit claim is
    # incorrect. Keep the original whole caveat in the durable repair audit.
    parts = re.split(r'(?<=[.;!?])\s+', copy)
    return ' '.join(_repair_clause(part, observations) for part in parts)


def reconcile_audit_scope(result, plan):
    """Repair topic/theme qualifiers while retaining original copy in audit."""
    by_id = {o.id: o for o in result.observations}
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    _, lookup = series_directory(result)
    groups = []
    if result.presentation_topics:
        groups += [(topic, [o for sid in topic.series_ids for o in lookup.get(sid, [])])
                   for topic in result.presentation_topics.topics]
    groups += [(theme, [by_id[oid] for oid in theme.observation_ids if oid in by_id])
               for theme in plan.themes]
    for owner, observations in groups:
        originals = list(owner.caveats)
        corrected = list(dict.fromkeys(_repair(copy, observations) for copy in originals))
        if originals == corrected:
            continue
        owner.caveats = corrected
        issue = ValidationIssue(code='presentation_audit_scope_repaired', severity='info', stage='presentation',
            related_ids=[owner.id], message=json.dumps({'original': originals, 'corrected': corrected}, ensure_ascii=False))
        if issue not in result.validation_warnings:
            result.validation_warnings.append(issue)
