"""Bounded literal identity context for model-owned display-name decisions."""
import hashlib
import json


def name_evidence(result):
    if not result.presentation_plan:
        return []
    company = result.presentation_plan.company
    name = company.name.strip()
    if not name:
        return []
    pages = set(company.source_pages) | set(company.field_source_pages.get('name', []))
    records = []
    for page in result.document.pages:
        if page.page_number not in pages:
            continue
        start = page.text.find(name)
        if start < 0:
            continue
        # Adjacent source wording can contain an official alternate-language
        # name. Only the model may decide whether it denotes the same entity.
        records.append({'page': page.page_number, 'literal_name': name,
                        'quote': page.text[max(0, start - 280):start + len(name) + 280]})
        if len(records) == 3:
            break
    return records


def context_fingerprint(language, evidence):
    payload = json.dumps({'contract': 'reviewed-name-evidence-v1', 'language': language,
                          'evidence': evidence}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
