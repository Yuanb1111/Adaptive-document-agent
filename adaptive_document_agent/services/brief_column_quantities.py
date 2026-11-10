"""Bind an immediately following bare cell to an explicit positioned unit header."""
from math import isfinite
import re

from adaptive_document_agent.extraction.normalizer import infer_unit_defaults
from adaptive_document_agent.extraction.numeric_parser import parse_number
from adaptive_document_agent.extraction.source_geometry import rotate_box
from .source_quotes import normalize_quote

_HEADER = re.compile(r'\(?\s*(?:[A-Z]{3}|US\$|HK\$|S\$|[$€£¥￥])\s+(?:in\s+)?'
                     r'(?:thousand|million|billion|trillion)s?\s*\)?', re.I)
_CELL = re.compile(r'[+−-]?\d[\d,]*(?:\.\d+)?|\(\d[\d,]*(?:\.\d+)?\)')
_HEADER_START = re.compile(r'^\(?\s*(?:[A-Z]{3}|US\$|HK\$|S\$|[$€£¥￥])(?:\s+|$)', re.I)
_SCALES = {1000: 'thousand', 1_000_000: 'million', 1_000_000_000: 'billion', 1_000_000_000_000: 'trillion'}


def _contains_line(text, line):
    return re.search(r'(?<!\S)' + re.escape(normalize_quote(line)) + r'(?!\S)', text) is not None


def column_quantities(page):
    """Return geometry evidence, never inferred row meaning or project ownership.

    Only the first adjacent cell under a complete standalone unit declaration
    qualifies. Missing geometry, intervening text and competing cells fail closed.
    Coordinates are rotated into reading orientation without changing the source.
    """
    if page.reading_rotation not in (0, 90, 180, 270):
        return []
    lines = []
    original = normalize_quote(page.text)
    for block in page.text_blocks:
        candidates = block.get('lines')
        if not isinstance(candidates, (list, tuple)):
            continue
        for line in candidates:
            if not isinstance(line, dict):
                continue
            text, box = line.get('text'), line.get('bbox')
            if (not isinstance(text, str) or not text.strip() or not isinstance(box, (list, tuple))
                    or len(box) != 4 or any(type(v) not in (int, float) or not isfinite(v) for v in box)
                    or box[0] >= box[2] or box[1] >= box[3]):
                continue
            if not _contains_line(original, text):
                continue
            lines.append((text.strip(), rotate_box(box, 0, 0, page.reading_rotation)))
    lines.sort(key=lambda line: (line[1][1], line[1][0]))

    def aligned(a, b):
        overlap = min(a[2], b[2]) - max(a[0], b[0])
        return overlap >= .8 * min(a[2] - a[0], b[2] - b[0])

    found = []
    for start, (text, box) in enumerate(lines):
        if not _HEADER_START.match(text):
            continue
        parts, indexes, last = [text], [start], box
        for _ in range(3):
            header = ' '.join(parts)
            if _HEADER.fullmatch(header):
                break
            following = [(i, t, b) for i, (t, b) in enumerate(lines) if i not in indexes
                         and aligned(box, b) and 0 <= b[1] - last[3] <= 2 * min(b[3]-b[1], last[3]-last[1])]
            if not following:
                break
            nearest = min(b[1] for _, _, b in following)
            following = [v for v in following if abs(v[2][1] - nearest) < .5]
            if len(following) != 1:
                break
            i, t, last = following[0]
            indexes.append(i)
            parts.append(t)
        if not _HEADER.fullmatch(header):
            continue
        defaults = infer_unit_defaults(header)
        if not defaults.currency or defaults.scale not in _SCALES:
            continue
        left, right = min(lines[i][1][0] for i in indexes), max(lines[i][1][2] for i in indexes)
        following = [(i, t, b) for i, (t, b) in enumerate(lines) if i not in indexes
                     and aligned((left, last[1], right, last[3]), b)
                     and 0 <= b[1] - last[3] <= 2 * min(b[3]-b[1], last[3]-last[1])]
        if not following:
            continue
        nearest = min(b[1] for _, _, b in following)
        following = [v for v in following if abs(v[2][1] - nearest) < .5]
        if len(following) != 1:
            continue
        _, raw, cell = following[0]
        if not _CELL.fullmatch(raw) or cell[0] < left - .5 or cell[2] > right + .5:
            continue
        parsed = parse_number(raw.replace('−', '-'))
        if parsed is not None:
            found.append(dict(raw_value=raw, currency=defaults.currency, unit=_SCALES[defaults.scale],
                evidence_lines=[*parts, raw], value_bbox=list(cell)))
    # Overlapping/competing declarations cannot confer two units on one cell.
    return [v for v in found if sum(other['value_bbox'] == v['value_bbox'] for other in found) == 1]


def quoted_column_quantities(page, quote, source):
    from .brief_table_evidence import canonical_quantity, _number
    quoted, original = normalize_quote(quote), normalize_quote(source)
    return {canonical_quantity(v['currency'], _number(parse_number(v['raw_value'].replace('−', '-')).value), v['unit'])
            for v in column_quantities(page)
            if all(_contains_line(quoted, line) and _contains_line(original, line)
                   for line in v['evidence_lines'])}
