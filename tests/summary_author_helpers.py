"""Synthetic author self-references, deliberately separate from semantic review verdicts."""
from copy import deepcopy
import json


def authored_test_draft(draft, messages):
    """Echo the test writer's source ownership and visible copy, never grant coverage approval."""
    meanings, owners = {}, {}
    for message in messages:
        try:
            payload = json.loads(message['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        except (IndexError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for part in payload.get('parts', []):
            if isinstance(part, dict) and part.get('required_meanings'):
                meanings[part['id']] = part['required_meanings']
                owners.update({fact['id']: part['id'] for fact in part['facts']})
        meanings.update(payload.get('required_meanings', {}))
        owners.update({fact['id']: fact['part_id'] for fact in payload.get('source_facts', [])})
    candidate = deepcopy(draft)
    for page in candidate['pages']:
        for item in page['items']:
            item['meaning_refs'] = [dict(part_id=part_id, meaning_index=index, summary_quote=item['text'])
                for part_id in dict.fromkeys(owners[fid] for fid in item['fact_ids'] if fid in owners)
                for index in range(len(meanings.get(part_id, [])))]
    return candidate
