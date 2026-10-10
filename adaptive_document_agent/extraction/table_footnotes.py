"""Retain literal small-print annotations with their physical source table."""
import re
from statistics import median
from collections import Counter

from .borderless_layout import source_lines


def retain_table_footnotes(page, tables):
    """Use numbered markers, font size and table geometry, never topic words.

    Annotations stay separate from analytical rows. A following table, heading,
    larger body font or distant paragraph ends the annotation. Without geometry
    or font evidence we do not infer that narrative prose is a table footnote.
    """
    chars = getattr(page, 'chars', [])
    positioned = [table for table in tables if table.bbox]
    if not chars or not positioned:
        return
    fonts = Counter(round(float(c['size']),1) for c in chars
                    if c.get('size') and str(c.get('text', '')).strip())
    if not fonts:
        return
    normal_size = max(size for size,count in fonts.items() if count >= sum(fonts.values())*.05)
    lines = source_lines(page, '', lambda s: s.strip())
    owner, paragraph, note_size, previous = None, [], None, None

    def flush():
        if owner is not None and paragraph:
            owner.raw_footnotes.append('\n'.join(paragraph))
        paragraph.clear()

    for line in lines:
        if line.top is None or not line.spans:
            continue
        sizes = [float(c['size']) for c in chars if c.get('size')
                 and line.top - 1 <= float(c.get('top', -100)) <= line.bottom + 1
                 and str(c.get('text', '')).strip()]
        size = median(sizes) if sizes else normal_size
        within_table = any(t.bbox[1] - 1 <= line.top <= t.bbox[3] + 1 for t in positioned)
        marker = re.match(r'^\(\d+\)(?:\s|$)', line.text)
        if marker and not within_table and size < normal_size * .96:
            flush()
            preceding = [t for t in positioned if t.bbox[3] < line.top]
            owner = max(preceding, key=lambda t: t.bbox[3]) if preceding else None
            note_size = size
            paragraph.append(line.text)
        elif paragraph:
            if (within_table or size > note_size + .3 or previous is None
                    or line.top - previous > 16
                    or re.fullmatch(r'[–—-]\s*\d+\s*[–—-]', line.text)):
                flush()
                owner = None
            else:
                paragraph.append(line.text)
        previous = line.bottom
    flush()
