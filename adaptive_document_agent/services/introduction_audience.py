"""Separate complete source reading from independently reviewed audience selection."""
import json
from hashlib import sha256


def reading_fingerprint(review):
    value = {'document':review.document_sha256, 'blocks':[b.model_dump() for b in review.source_blocks],
             'parts':[p.model_dump(exclude={'facts'}) for p in review.parts]}
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def audience_part_ids(review):
    content = {p.id for p in review.parts if p.role == 'content'}
    if review.audience_part_ids is None:
        return content
    selected = set(review.audience_part_ids)
    audit = review.audience_selection
    decisions = audit.get('decisions', [])
    if (not selected or len(selected) != len(review.audience_part_ids) or not selected <= content
            or audit.get('reading_fingerprint') != reading_fingerprint(review)
            or audit.get('independent_review', {}).get('accepted') is not True
            or len(decisions) != len(content) or {d.get('part_id') for d in decisions} != content
            or {d['part_id'] for d in decisions if d.get('include') is True} != selected
            or any(type(d.get('include')) is not bool or not d.get('reason','').strip() for d in decisions)):
        raise ValueError('Introduction audience selection lacks complete current source decisions and independent review')
    return selected
