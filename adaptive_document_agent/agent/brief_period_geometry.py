"""Read exact closing dates from the original item's quoted table headers."""
from datetime import date
from math import isfinite
import re

from adaptive_document_agent.extraction.borderless_layout import source_lines
from adaptive_document_agent.extraction.period_header_geometry import geometric_periods
from adaptive_document_agent.services.source_quotes import continuous_quote_passages, normalize_quote

_MONTHS = 'January February March April May June July August September October November December'.split()
_DATE = re.compile(r'\b(' + '|'.join(_MONTHS) + r')\s+(\d{1,2})\b', re.I)
_YEAR = re.compile(r'\b(?:19|20)\d{2}\b')


def _box(value):
    return (isinstance(value, (list, tuple)) and len(value) == 4
            and all(isinstance(v, (int, float)) and isfinite(v) for v in value)
            and value[0] <= value[2] and value[1] <= value[3])


def quoted_table_period_identities(item, result, inventory):
    """Only bind dates where independent duration and year geometry agree.

    This supplies aliases of existing displayed periods, never an audit status,
    new period, measurement or semantic judgment. Split lines remain literal.
    """
    if result is None:
        return set()
    pages = {p.page_number: p for p in result.document.pages}
    passages = continuous_quote_passages(item.evidence, {n: p.text for n, p in pages.items()})
    compact = lambda text: ''.join(normalize_quote(text).split())
    identities = set()
    for entry in inventory:
        page = pages.get(entry['page'])
        if page is None or page.reading_rotation:
            continue
        table = next((t for t in page.tables if t.table_id == entry['table_id']), None)
        if table is None or table.source_rotation or not _box(table.bbox):
            continue
        words = [dict(text=line['text'], x0=line['bbox'][0], x1=line['bbox'][2],
                      top=line['bbox'][1], bottom=line['bbox'][3])
                 for block in page.text_blocks if isinstance(block, dict)
                 for line in block.get('lines', []) if isinstance(line, dict)
                 and _box(line.get('bbox')) and isinstance(line.get('text'), str) and line['text'].strip()]
        if not words:
            continue
        lines = source_lines(page, page.text, str.strip, words=words)
        quoted = [compact(q.text) for q in passages if q.page == page.page_number]
        raw_headers = {compact(raw) for raw in table.raw_header_lines}
        candidates = [i for i, line in enumerate(lines) if len(_YEAR.findall(line.text)) >= 2
                      and compact(line.text) in raw_headers and line.bottom is not None
                      and line.bottom < table.bbox[1] and any(compact(line.text) in q for q in quoted)]
        if not candidates:
            continue
        index = max(candidates, key=lambda i: lines[i].bottom)
        year_line = lines[index]
        tiers = []
        for line in reversed(lines[max(0, index - 5):index]):
            if len(line.text) > 95 or line.text.endswith('.') or _YEAR.search(line.text):
                break
            if compact(line.text) not in raw_headers or not any(compact(line.text) in q for q in quoted):
                break
            tiers.insert(0, line)
        width = len(table.headers) - 1
        actual = geometric_periods(tiers, year_line, width)
        stored = [re.sub(r'\s+', '', p or '').upper() for p in table.column_periods[1:]]
        if not actual or actual != stored:
            continue
        years = list(_YEAR.finditer(year_line.text))
        boxes = [year_line.bounds(m.start(), m.end()) for m in years]
        if not boxes or not all(boxes) or width % len(years):
            continue
        centers = [(a + b) / 2 for a, b in boxes]
        gap = min((b - a for a, b in zip(centers, centers[1:])), default=0)
        labels = actual[::width // len(years)]
        groups = []
        for i, label in enumerate(labels):
            prefix = re.sub(r'(?:19|20)\d{2}$', '', label)
            if not groups or groups[-1][0] != prefix:
                groups.append((prefix, []))
            groups[-1][1].append(i)
        dates = []
        for line in tiers:
            for match in _DATE.finditer(line.text):
                spans = [s for s in line.spans if s[0] < match.end() and s[1] > match.start()]
                if spans:
                    dates.append(((spans[0][2] + spans[-1][3]) / 2,
                                  _MONTHS.index(match[1].capitalize()) + 1, int(match[2])))
        dates = sorted(set(dates))
        if gap <= 0 or len(dates) != len(groups) or any(
                abs(sum(centers[i] for i in group) / len(group) - x) > .6 * gap
                for (_, group), (x, _, _) in zip(groups, dates)):
            continue
        for (prefix, group), (_, month, day) in zip(groups, dates):
            duration = re.fullmatch(r'(1[0-2]|[1-9])M', prefix)
            if duration:
                for i in group:
                    try:
                        closing = date(int(years[i][0]), month, day).isoformat()
                    except ValueError:
                        continue
                    identities.add((int(duration[1]), closing))
    return identities
