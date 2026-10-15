"""Explicit current-draft binding for synthetic introduction reviewer responses."""
import json


def review_payload(messages):
    return json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


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
