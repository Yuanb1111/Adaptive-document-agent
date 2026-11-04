"""Reading-order coordinates for quoted text on rotated PDF pages."""
from math import isfinite

from adaptive_document_agent.extraction.source_geometry import rotate_box
from adaptive_document_agent.services.source_quotes import normalize_quote


def quoted_layout(item, result):
    if result is None:
        return []
    quoted = {}
    for q in item.evidence:
        quoted.setdefault(q.page, []).append(normalize_quote(q.text))
    layout = []
    for page in result.document.pages:
        if page.page_number not in quoted or page.reading_rotation not in (90, 180, 270):
            continue
        lines = []
        for block in page.text_blocks:
            if not isinstance(block, dict) or not isinstance(block.get('lines'), list):
                continue
            for line in block['lines']:
                if not isinstance(line, dict):
                    continue
                box, text = line.get('bbox'), line.get('text')
                if (not isinstance(box, (tuple, list)) or len(box) != 4
                        or not all(isinstance(n, (float, int)) and isfinite(n) for n in box)
                        or box[0] > box[2] or box[1] > box[3]
                        or not isinstance(text, str) or not text.strip()
                        or not any(normalize_quote(text) in q for q in quoted[page.page_number])):
                    continue
                # A common translation of every box leaves column alignment
                # unchanged. Page dimensions need not be inferred.
                x, y, right, _ = rotate_box(box, 0, 0, page.reading_rotation)
                lines.append([round(y, 1), round(x, 1), round(right, 1), text])
        if lines:
            layout.append(dict(page=page.page_number, lines=sorted(lines)))
    return layout


LAYOUT_RULE = ('quoted_layout gives [y, left, right, literal text] in the rotated page\'s reading orientation. '
    'Match entries to their own column headers. Distinguish separate activities and the subject of each verb. '
    'Items in the same period do not establish a before/after sequence. If a column or sequence is ambiguous, '
    'state only the supported scope. Keep any metric-specific basis attached to that metric when explaining changes.')
