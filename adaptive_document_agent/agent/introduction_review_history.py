"""Compact invocation-owned review context, never reusable semantic acceptance."""
from copy import deepcopy
from hashlib import sha256
import json

from pydantic import ValidationError

from adaptive_document_agent.services.introduction_audience import reading_fingerprint, selection_digest
from adaptive_document_agent.services.source_quotes import normalize_quote


def review_context_identity(source, rules, review):
    """Bind history to complete reading, audience purpose, page budget and rules."""
    reading = reading_fingerprint(review)
    context = dict(reading_fingerprint=reading, maximum_intro_slides=review.max_intro_slides,
                   source=source, review_rules=rules)
    return dict(reading_fingerprint=reading, context_digest=sha256(json.dumps(
        context, sort_keys=True, ensure_ascii=False).encode()).hexdigest())


def prior_bound_history(review, source, values, context_identity, flow_id):
    """Expose only verified historical verdicts from this exact local review flow.

    Source passages stay in source.parts. Historical assertion identifiers are
    explicitly local to each old selection digest and cannot address current copy.
    Only exact textual equality is reported; the new reviewer judges meaning.
    """
    from .introduction_audience_review import IntroductionAudienceReview, binding_errors, current_meanings
    current = {decision['part_id']: decision for decision in values}
    current_rows = current_meanings(values)
    parts = {part['id']: part for part in source['parts']}
    history = []
    for audit in review.plan_audits:
        record = audit.get('introduction_audience_review', {})
        if (record.get('flow_id') != flow_id or record.get('context_identity') != context_identity
                or record.get('status') != 'bound' or record.get('binding_errors') != []):
            continue
        decisions = record.get('decisions')
        if not isinstance(decisions, list):
            continue
        try:
            digest = selection_digest(review, decisions)
            verdict = IntroductionAudienceReview.model_validate(record.get('review'))
            payload = dict(source=source, decisions=decisions, current_meanings=current_meanings(decisions),
                           current_selection_digest=digest)
            if digest != record.get('selection_digest') or binding_errors(verdict, payload):
                continue
        except (ValidationError, ValueError, KeyError, TypeError):
            continue
        before = {decision['part_id']: decision for decision in decisions}
        scope_deltas = [dict(part_id=part_id, previous_include=decision['include'],
                             previous_reason=decision['reason']) for part_id, decision in before.items()
                        if part_id not in current or (decision['include'], decision['reason']) != (
                            current[part_id]['include'], current[part_id]['reason'])]
        findings = []
        for index, finding in enumerate(verdict.findings):
            quote = normalize_quote(finding.source_quote)
            start = normalize_quote(parts[finding.part_id]['source_text']).find(quote)
            row = dict(historical_finding_id=f'finding-{index}', kind=finding.kind,
                       issue_type=finding.issue_type, part_id=finding.part_id, reason=finding.reason,
                       source_part_ref=finding.part_id, source_normalized_span=[start, start + len(quote)],
                       current_part_copy_unchanged=[m['meaning'] for m in before[finding.part_id]['required_meanings']]
                       == [m['meaning'] for m in current.get(finding.part_id, {}).get('required_meanings', [])])
            if finding.kind == 'meaning':
                exact = [m['meaning_id'] for m in current_rows
                         if m['part_id'] == finding.part_id and m['meaning'] == finding.current_meaning]
                row.update(historical_meaning_ref=f'{digest}/{finding.meaning_id}',
                           historical_meaning=finding.current_meaning,
                           exact_current_meaning_ids=exact,
                           historical_text_present_in_current_part=bool(exact),
                           current_part_meaning_ids=[m['meaning_id'] for m in current_rows
                               if m['part_id'] == finding.part_id])
            findings.append(row)
        history.append(dict(round=record['round'], historical_namespace=digest,
            accepted=verdict.accepted, reason=verdict.reason, repair_scope=verdict.repair_scope,
            source_and_section_context_unchanged=True, scope_deltas=scope_deltas,
            findings=findings, semantic_approval_for_current_selection=False))
    return history


def decision_references(decisions, rows):
    """Replace repeated copy with complete exact ordered IDs in one explicit namespace."""
    inventory = {row['meaning_id']: row for row in rows}
    if len(inventory) != len(rows):
        raise ValueError('Review meaning namespace contains repeated IDs')
    referenced, wire = [], []
    for decision in decisions:
        ids, metadata = [], []
        for index, meaning in enumerate(decision['required_meanings']):
            identifier = f"{decision['part_id']}:meaning-{index+1}"
            row = inventory.get(identifier)
            if (row is None or row['part_id'] != decision['part_id'] or row['meaning'] != meaning['meaning']
                    or row.get('meaning_index', index) != index):
                raise ValueError('Review decision does not match its exact ordered owned meaning ID')
            ids.append(identifier)
            extra = {key: deepcopy(item) for key, item in meaning.items() if key not in {'meaning', 'source_quote'}}
            if extra:
                metadata.append(dict(meaning_id=identifier, fields=extra))
        row = {key: deepcopy(item) for key, item in decision.items() if key != 'required_meanings'}
        row['required_meaning_ids'] = ids
        if metadata:
            row['meaning_metadata'] = metadata
        wire.append(row)
        referenced.extend(ids)
    if len(referenced) != len(set(referenced)) or set(referenced) != set(inventory):
        raise ValueError('Review decisions must reference every exact meaning once')
    return wire


def resolution_wire(resolution):
    """Reference exact immutable before-meaning rows instead of repeating their copy."""
    if resolution is None:
        return None
    value = deepcopy(resolution)
    rows = value.get('before_resolution_meanings')
    if rows is None or value.get('reference_namespace') != 'before_resolution_meanings':
        return value
    value['decisions_before'] = decision_references(value['decisions_before'], rows)
    value['decisions_before_namespace'] = 'before_resolution_meanings'
    return value
