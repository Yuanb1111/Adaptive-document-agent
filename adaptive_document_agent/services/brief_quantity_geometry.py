"""Bind an explicit money coefficient to its immediately wrapped scale block."""
import re

from .source_quotes import normalize_quote


def wrapped_quantity_support(page, quote, source):
    """Use unique same-column geometry, never proximity in flattened PDF text.

    Both complete blocks must occur in the cited passage and source excerpt.
    A bare number or a table-wide unit header cannot use this narrow recovery.
    """
    from .executive_brief import _QUANTITY, _quantities
    from .brief_table_evidence import canonical_quantity
    quoted, original = normalize_quote(quote), normalize_quote(source)
    blocks = []
    source_lines = [line for block in page.text_blocks for line in (block.get('lines') or [block])]
    for block in source_lines:
        box = block.get('bbox')
        text = str(block.get('text', '')).strip()
        if (not box or len(box) != 4 or not all(isinstance(v, (int, float)) for v in box)
                or box[2] <= box[0] or box[3] <= box[1] or not text):
            continue
        blocks.append((text, box))
    pairs = []
    for text, box in blocks:
        match = _QUANTITY.fullmatch(text)
        if not match or not (match['currency'] or match['currency_suffix']) or match['unit']:
            continue
        for unit, ub in blocks:
            if not re.fullmatch(r'thousand|million|billion|trillion|千|百万|十亿|万亿', unit, re.I):
                continue
            overlap = min(box[2], ub[2]) - max(box[0], ub[0])
            if overlap < .8 * min(box[2]-box[0], ub[2]-ub[0]):
                continue
            if not 0 <= ub[1] - box[3] <= 1.2 * min(box[3]-box[1], ub[3]-ub[1]):
                continue
            if any(b != box and b != ub and b[1] < ub[1] and b[3] > box[3]
                   and min(b[2], box[2]) > max(b[0], box[0]) for _, b in blocks):
                continue
            pairs.append((text, box, unit, ub))
    supported = set()
    for text, box, unit, ub in pairs:
        if sum(b == box or u == ub for _, b, _, u in pairs) != 1:
            continue
        if not all(normalize_quote(t) in quoted and normalize_quote(t) in original for t in (text, unit)):
            continue
        supported.update(canonical_quantity(*q) for q in _quantities(text + ' ' + unit))
    return supported
