"""Synthetic author self-references, deliberately separate from semantic review verdicts."""
from copy import deepcopy
import json


def writer_test_value(schema, value):
    """Adapt only redundant quotation transport in explicitly address-only writers."""
    if 'SummaryWriterMeaningRef' in schema.model_json_schema().get('$defs', {}):
        from adaptive_document_agent.agent.summary_writer_copy import address_only_copy
        value = address_only_copy(value)
        if any('display' in definition.get('required', [])
               for definition in schema.model_json_schema().get('$defs', {}).values()):
            # Synthetic writers explicitly choose ordinary paragraphs. This
            # transport hint neither invents a semantic structure nor grants
            # any independent coverage/meaning acceptance.
            def display(node):
                if isinstance(node, dict):
                    if 'text' in node and 'fact_ids' in node and node.get('display') is None:
                        node['display'] = {'layout': 'paragraphs', 'break_after': []}
                    for child in node.values():
                        display(child)
                elif isinstance(node, list):
                    for child in node:
                        display(child)
            display(value)
        return value
    return value


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
        for row in payload.get('layout_feedback', {}).get('meaning_inventory', []):
            values = meanings.setdefault(row['part_id'], [])
            while len(values) <= row['meaning_index']:
                values.append({})
            values[row['meaning_index']] = {'meaning': row['meaning']}
        owners.update({fact['id']: fact['part_id'] for fact in payload.get('source_facts', [])})
    candidate = deepcopy(draft)
    for page in candidate['pages']:
        for item in page['items']:
            if item.get('display') is None:
                item['display'] = {'layout': 'paragraphs', 'break_after': []}
            item['meaning_refs'] = [dict(part_id=part_id, meaning_index=index)
                for part_id in dict.fromkeys(owners[fid] for fid in item['fact_ids'] if fid in owners)
                for index in range(len(meanings.get(part_id, [])))]
    return candidate
