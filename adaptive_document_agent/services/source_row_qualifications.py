"""Retain literal row footnotes that qualify the displayed measure's scope."""

import re


def source_row_qualifications(observations, document, *, pages=None):
    pages = pages if pages is not None else {page.page_number: page for page in document.pages}
    notes, seen = [], set()
    for item in observations:
        for evidence in item.evidence:
            page = pages.get(evidence.page)
            table = next((t for t in page.tables if t.table_id == evidence.table_id), None) if page else None
            if table is None or not evidence.row_label:
                continue
            label = r'\s+'.join(re.escape(word) for word in evidence.row_label.split())
            markers = re.findall(r'(?<!\w)' + label + r'\s*\((\d+)\)', '\n'.join(table.raw_body_lines), re.I)
            if len(set(markers)) != 1:
                continue
            marker = markers[0]
            matches = list(re.finditer(r'(?m)^\s*\(' + re.escape(marker) + r'\)\s+', page.text))
            if len(matches) != 1:
                continue
            tail = page.text[matches[0].end():]
            # Only the complete first source sentence, never a clipped qualifier
            # or the next note/running header. Long notes stay in source evidence.
            end = re.search(r'\.(?=\s|$)', tail)
            if end is None or re.search(r'(?m)^\s*\(\d+\)', tail[:end.end()]):
                continue
            quote = ' '.join(tail[:end.end()].split())
            key = (evidence.page, evidence.table_id, marker)
            if not quote or len(quote) > 550 or key in seen:
                continue
            seen.add(key)
            notes.append({'label': evidence.row_label, 'text': quote, 'page': evidence.page,
                          'table_id': evidence.table_id, 'marker': marker})
    return notes
