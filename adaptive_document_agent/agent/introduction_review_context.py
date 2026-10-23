"""Separate historical drafts and mechanical binding feedback from current copy."""
from collections import Counter
from copy import deepcopy

from adaptive_document_agent.services.source_quotes import normalize_quote


def bind_finding_sources(verdict, payload):
    """Materialize explicit empty-quote references without rewriting model judgments.

    Nonempty model quotations still face literal validation. Unknown/ambiguous
    owners and stale meaning IDs remain errors; no nearest source is inferred.
    """
    counts = Counter(part['id'] for part in payload['source']['parts'])
    parts = {part['id']: part for part in payload['source']['parts']}
    bound = verdict.model_copy(deep=True)
    bindings = []
    for index, finding in enumerate(bound.findings):
        if finding.source_quote != '' or counts[finding.part_id] != 1:
            continue
        part = parts[finding.part_id]
        if not normalize_quote(part['source_text']):
            continue
        finding.source_quote = part['source_text']
        bindings.append(dict(finding_index=index, source_part_ref=finding.part_id,
                             binding='complete_owned_source', semantic_approval=False))
    return bound, bindings


def historical_context(meaning_base, inventory_base, resolution, history):
    """Preserve complete historical meaning without presenting it as current copy."""
    from .introduction_audience_review import selection_wire
    return dict(reference_role='historical_preservation_only',
        semantic_approval_for_current_selection=False,
        meaning_revision_base=selection_wire(meaning_base),
        inventory_revision_base=selection_wire(inventory_base),
        meaning_resolution=resolution, prior_bound_reviews=history)


def binding_recheck(verdict, payload, errors):
    """Report exact address/text conflicts, never infer a corrected semantic verdict.

    A matching current ID is only a lookup: it cannot rebind a stale finding to
    changed text or establish that either wording is supported by the source.
    """
    meanings = {row['meaning_id']: row for row in payload['current_meanings']}
    parts = {part['id']: part for part in payload['source']['parts']}
    decisions = {row['part_id']: row for row in payload['decisions']}
    conflicts = []
    for index, finding in enumerate(verdict.findings):
        current = meanings.get(finding.meaning_id)
        part = parts.get(finding.part_id)
        decision = decisions.get(finding.part_id)
        quote = normalize_quote(finding.source_quote)
        conflicts.append(dict(finding_index=index, returned_kind=finding.kind,
            returned_part_id=finding.part_id, returned_meaning_id=finding.meaning_id,
            returned_current_meaning=finding.current_meaning,
            returned_source_quote=finding.source_quote,
            source_part_ref=finding.part_id if part is not None else None,
            exact_current_target=deepcopy(current),
            current_target_owner_matches=current is not None and current['part_id'] == finding.part_id,
            current_target_text_matches=current is not None and current['meaning'] == finding.current_meaning,
            current_part_include=decision['include'] if decision is not None else None,
            current_part_meaning_ids=[row['meaning_id'] for row in payload['current_meanings']
                                      if row['part_id'] == finding.part_id],
            source_quote_is_literal=bool(part and quote and quote in normalize_quote(part['source_text']))))
    return dict(current_selection_digest=payload['current_selection_digest'],
        returned_selection_digest=verdict.selection_digest, binding_errors=list(errors),
        source_quote_contract='empty_references_complete_owned_part; nonempty_must_be_continuous_literal',
        full_source_review_required=True, semantic_approval=False, findings=conflicts)
