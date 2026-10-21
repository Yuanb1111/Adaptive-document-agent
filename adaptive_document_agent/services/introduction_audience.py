"""Separate complete source reading from independently reviewed audience selection."""
import json
from hashlib import sha256
from .source_quotes import normalize_quote


def validate_required_meanings(review, decisions):
    parts = {p.id: p for p in review.parts}
    for decision in decisions:
        meanings = decision.get('required_meanings', [])
        if bool(meanings) != decision.get('include'):
            raise ValueError('Introduction selection requires source-bound central meanings for every included part')
        seen = set()
        for value in meanings:
            meaning = value.get('meaning', '').strip()
            quote = normalize_quote(value.get('source_quote', ''))
            if (not meaning or meaning in seen or not quote
                    or quote != normalize_quote(parts[decision['part_id']].source_text)):
                raise ValueError('Introduction required meaning lacks its exact owned source quotation')
            seen.add(meaning)


def required_meanings(review):
    return {d['part_id']: d['required_meanings'] for d in review.audience_selection.get('decisions', [])
            if d['include']}


def meanings_digest(review):
    return sha256(json.dumps(required_meanings(review), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def coverage_errors(verdict, meanings, pages):
    checks = verdict.get('coverage', [])
    indices = [c.get('meaning_index') for c in checks]
    if len(indices) != len(meanings) or set(indices) != set(range(len(meanings))):
        return ['Central-meaning review must check every exact meaning index once']
    bound, groups = [], {}
    for page in pages:
        for item in page.items:
            if verdict['part_id'] not in item.part_ids:
                continue
            group = getattr(item, 'continuation_group', '')
            if group:
                if group not in groups:
                    groups[group] = []
                    bound.append(groups[group])
                groups[group].append(item)
            else:
                bound.append(item.text)
    actual = normalize_quote(' '.join(value if isinstance(value, str) else
        ''.join(item.text for item in sorted(value, key=lambda item: item.continuation_index)) for value in bound))
    errors = []
    for check in checks:
        meaning = meanings[check['meaning_index']]['meaning']
        quote = normalize_quote(check.get('summary_quote', ''))
        if check.get('covered') is not True:
            errors.append('Missing central meaning: ' + meaning + '. ' + check.get('reason', ''))
        elif check.get('paragraph_ids'):
            from .visible_summary_paragraphs import visible_paragraphs
            catalog = visible_paragraphs(pages)
            ids = check['paragraph_ids']
            if (len(ids) != len(set(ids)) or any(key not in catalog or verdict['part_id'] not in catalog[key]['part_ids'] for key in ids)
                    or quote != normalize_quote(' '.join(catalog[key]['text'] for key in ids if key in catalog))):
                errors.append('Central meaning has invalid current visible paragraph addresses: ' + meaning)
        elif not quote or quote not in actual:
            errors.append('Central meaning has no quoted visible paragraph bound to this part: ' + meaning)
    return errors


def reading_fingerprint(review):
    value = {'document':review.document_sha256, 'blocks':[b.model_dump() for b in review.source_blocks],
             'parts':[p.model_dump(exclude={'facts'}) for p in review.parts]}
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def selection_digest(review, decisions):
    """Bind approval to the full source, page budget and exact current decisions."""
    value = {'reading_fingerprint': reading_fingerprint(review),
             'maximum_intro_slides': review.max_intro_slides, 'decisions': decisions}
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def audience_part_ids(review):
    content = {p.id for p in review.parts if p.role == 'content'}
    if review.audience_part_ids is None and not review.audience_selection:
        return content
    selected = set(review.audience_part_ids or [])
    audit = review.audience_selection
    decisions = audit.get('decisions', [])
    if (not selected or len(selected) != len(review.audience_part_ids) or not selected <= content
            or audit.get('reading_fingerprint') != reading_fingerprint(review)
            or audit.get('independent_review', {}).get('accepted') is not True
            or audit.get('independent_review', {}).get('selection_digest') != selection_digest(review, decisions)
            or audit.get('independent_review', {}).get('findings') != []
            or len(decisions) != len(content) or {d.get('part_id') for d in decisions} != content
            or {d['part_id'] for d in decisions if d.get('include') is True} != selected
            or any(type(d.get('include')) is not bool or not d.get('reason','').strip() for d in decisions)):
        raise ValueError('Introduction audience selection lacks complete current source decisions and independent review')
    validate_required_meanings(review, decisions)
    return selected
