"""Bind reviewer-selected paragraph addresses and resolve quote-only disagreements."""
import json

from adaptive_document_agent.services.source_quotes import normalize_quote
from adaptive_document_agent.services.visible_summary_paragraphs import visible_paragraphs
from .prompting import untrusted_document_message


def coverage_review_messages(messages, pages):
    catalog = visible_paragraphs(pages)
    by_part = {}
    for paragraph in catalog.values():
        for part in paragraph['part_ids']:
            by_part.setdefault(part, []).append({'paragraph_id': paragraph['paragraph_id'], 'text': paragraph['text']})
    instructions = (' Review meaning across languages: source quotations and required meanings may be English '
        'while current visible paragraphs are Chinese, or vice versa. Use the supplied bound_visible_paragraphs '
        'catalog for each source part. For each covered meaning, choose the exact paragraph_ids that express '
        'it and leave summary_quote empty; Python binds their literal current text. Do not copy or translate '
        'a source quotation into summary_quote. A quotation/address failure is a review protocol error, '
        'not proof of missing content. Independently decide whether the bound visible paragraphs preserve '
        'the meaning and qualifications. Empty paragraph_ids and covered=false remain mandatory when missing.')
    updated = [dict(m) for m in messages]
    updated[0]['content'] += instructions
    for index in range(len(updated) - 1, -1, -1):
        content = updated[index]['content']
        if not content.startswith('<UNTRUSTED_DOCUMENT_CONTENT>'):
            continue
        try:
            payload = json.loads(content.split('\n', 1)[1].rsplit('\n', 1)[0])
        except (ValueError, IndexError):
            continue
        if isinstance(payload, dict) and 'source' in payload and 'pages' in payload:
            payload['bound_visible_paragraphs'] = by_part
            updated[index] = untrusted_document_message(json.dumps(payload, ensure_ascii=False))
            break
    else:
        raise ValueError('Coverage review requires its complete current source and visible-copy payload')
    return updated, catalog


def bind_coverage_paragraphs(response, catalog):
    from .compact_summary_review import ReviewTargetError
    count = 0
    for verdict in response.parts:
        for check in verdict.coverage:
            ids = check.paragraph_ids
            if not ids:
                continue  # Existing saved reviews retain strict literal-quote validation.
            if (check.covered is not True or len(ids) != len(set(ids))
                    or any(key not in catalog or verdict.part_id not in catalog[key]['part_ids'] for key in ids)):
                raise ReviewTargetError('Coverage paragraph addresses must be unique, current and bound to the reviewed part')
            check.summary_quote = ' '.join(catalog[key]['text'] for key in ids)
            count += 1
    return count


def invalid_visible_quote_pairs(response, catalog):
    pairs = set()
    for verdict in response.parts:
        text = normalize_quote(' '.join(row['text'] for row in catalog.values() if verdict.part_id in row['part_ids']))
        for check in verdict.coverage:
            if check.covered and not check.paragraph_ids:
                quote = normalize_quote(check.summary_quote)
                if text and (not quote or quote not in text):
                    pairs.add((verdict.part_id, check.meaning_index))
    return pairs


def quote_disagreements(response, previous_pairs):
    return sorted((v.part_id, c.meaning_index) for v in response.parts for c in v.coverage
                  if not c.covered and (v.part_id, c.meaning_index) in previous_pairs)
