"""Explicit current-draft binding for synthetic introduction reviewer responses."""
import json


def review_payload(messages):
    payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    return materialize_review_wire(payload)


def materialize_review_wire(payload):
    # Synthetic legacy responders consume the canonical quote view. The real
    # wire keeps the complete owning passage only once under source.parts.
    # Legacy synthetic responders inspect canonical baseline names; production
    # requests isolate them under historical_context, never as current copy.
    for key in ('meaning_revision_base', 'inventory_revision_base', 'meaning_resolution', 'prior_bound_reviews'):
        if key in payload.get('historical_context', {}):
            payload.setdefault(key, payload['historical_context'][key])
    sources = {part['id']: part['source_text'] for part in payload.get('source', {}).get('parts', [])}
    for row in payload.get('current_meanings', []):
        row.setdefault('source_quote', sources.get(row['part_id'], ''))
    def references(values, inventory):
        for decision in values:
            metadata = {row['meaning_id']: row['fields'] for row in decision.pop('meaning_metadata', [])}
            decision['required_meanings'] = [dict(meaning=inventory[identifier]['meaning'],
                source_quote=sources.get(decision['part_id'], ''), **metadata.get(identifier, {}))
                for identifier in decision.pop('required_meaning_ids')]
    def decisions(values):
        if isinstance(values, dict):
            decisions(values.get('decisions', []))
        elif isinstance(values, list):
            for decision in values:
                for meaning in decision.get('required_meanings', []):
                    meaning.setdefault('source_quote', sources.get(decision['part_id'], ''))
    if payload.get('current_selection_digest'):
        if payload.get('decisions_reference_namespace') == 'current_meanings':
            references(payload['decisions'], {row['meaning_id']: row for row in payload['current_meanings']})
        for field in ('decisions', 'meaning_revision_base', 'inventory_revision_base'):
            decisions(payload.get(field))
        resolution = payload.get('meaning_resolution')
        if resolution and resolution.get('decisions_before_namespace') == 'before_resolution_meanings':
            before = {row['meaning_id']: row for row in resolution['before_resolution_meanings']}
            references(resolution['decisions_before'], before)
            decisions(resolution['decisions_before'])
    return payload


def review_response(schema, messages, *, accepted, reason, repair_scope='selection', findings=None):
    payload = review_payload(messages)
    if findings is None:
        findings = []
        if not accepted:
            target = payload['current_meanings'][0]
            findings = [dict(kind='meaning', part_id=target['part_id'],
                meaning_id=target['meaning_id'], current_meaning=target['meaning'],
                source_quote=target['source_quote'], reason=reason)]
    return schema(accepted=accepted, reason=reason, repair_scope=repair_scope,
                  selection_digest=payload['current_selection_digest'], findings=findings)
