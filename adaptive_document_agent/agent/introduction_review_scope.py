"""Derive part placement from the exact current selection, preserving reviewer rejection."""
from collections import Counter

from adaptive_document_agent.services.source_quotes import normalize_quote


def bind_finding_scope(verdict, payload):
    """Bind redundant placement tags, never choose inclusion or repair source meaning.

    A part-level finding already identifies its owning source by ID. Its current
    include/omit state belongs to the selection ledger, not the reviewer. Keep
    the raw response in the caller's audit and preserve every semantic field.
    Unknown/ambiguous ownership, stale digests, meaning references and nonliteral
    evidence are left for binding validation; no alternate target is inferred.
    """
    bound = verdict.model_copy(deep=True)
    audit = dict(findings=[], semantic_approval=False)
    if bound.accepted or bound.selection_digest != payload['current_selection_digest']:
        return bound, audit
    part_counts = Counter(p['id'] for p in payload['source']['parts'])
    decision_counts = Counter(d['part_id'] for d in payload['decisions'])
    parts = {p['id']: p for p in payload['source']['parts']}
    decisions = {d['part_id']: d for d in payload['decisions']}
    omitted = []
    for index, finding in enumerate(bound.findings):
        if (finding.kind not in {'included_part', 'omitted_part'}
                or finding.meaning_id or finding.current_meaning
                or part_counts[finding.part_id] != 1 or decision_counts[finding.part_id] != 1):
            continue
        include = decisions[finding.part_id]['include']
        quote = normalize_quote(finding.source_quote)
        if (type(include) is not bool or not quote
                or quote not in normalize_quote(parts[finding.part_id]['source_text'])):
            continue
        expected = 'included_part' if include else 'omitted_part'
        if finding.kind != expected:
            audit['findings'].append(dict(finding_index=index, part_id=finding.part_id,
                returned_kind=finding.kind, current_kind=expected, current_include=include,
                selection_digest=payload['current_selection_digest']))
            finding.kind = expected
        if not include:
            omitted.append(finding.part_id)
    if omitted and bound.repair_scope != 'selection':
        audit['repair_scope'] = dict(returned=bound.repair_scope, current='selection',
            omitted_part_ids=list(dict.fromkeys(omitted)))
        # This only routes the rejection to a source-aware selection repair.
        # It does not include any part or authorize the next draft.
        bound.repair_scope = 'selection'
    return bound, audit
