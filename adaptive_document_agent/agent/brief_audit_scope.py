"""Keep assurance annotations on their source-bound reporting columns."""
import re
from math import isfinite
from datetime import date

from adaptive_document_agent.extraction.numeric_parser import parse_number
from adaptive_document_agent.extraction.period_header_geometry import MONTH_COUNTS, month_count
from adaptive_document_agent.services.brief_table_evidence import _header_dates, _located_header, _quoted_complete_row
from adaptive_document_agent.services.source_quotes import continuous_quote_passages, normalize_quote

_MONTHS = "January February March April May June July August September October November December".split()
_MONTH = "(?:" + "|".join(_MONTHS) + ")"
_YEAR = r"(?:19|20)\d{2}"
_DURATION = "(?:" + "|".join(MONTH_COUNTS) + r"|1[0-2]|[1-9])"
_CALENDAR_DATE = rf"{_MONTH}\s+\d{{1,2}},?\s+{_YEAR}"
_PERIOD = re.compile(
    rf"(?P<flow>{_DURATION}\s+months?\s+ended\s+{_CALENDAR_DATE})"
    rf"|(?P<label>(?:FY|[1-9]M|1[0-2]M|[12]H|H[12]|Q[1-4])\s*{_YEAR})"
    rf"|(?P<iso>{_YEAR}-\d{{2}}-\d{{2}})|(?P<date>{_CALENDAR_DATE})|(?P<year>{_YEAR})", re.I)
_STATUS = re.compile(r"\b(?:unaudited|audited)\b", re.I)


def _geometric_statuses(page, table, labels):
    """Recheck preserved coordinates before trusting a column annotation."""
    from adaptive_document_agent.extraction.borderless_layout import source_lines, geometric_audit_statuses
    words = []
    def valid_box(box):
        return (isinstance(box, (list, tuple)) and len(box) == 4
                and all(isinstance(v, (int, float)) and isfinite(v) for v in box)
                and box[0] <= box[2] and box[1] <= box[3])
    for block in page.text_blocks:
        if not isinstance(block, dict) or not isinstance(block.get('lines'), list):
            continue
        for line in block['lines']:
            if not isinstance(line, dict):
                continue
            box = line.get('bbox')
            if valid_box(box) and isinstance(line.get('text'), str) and line['text'].strip():
                words.append(dict(text=line['text'], x0=box[0], x1=box[2], top=box[1], bottom=box[3]))
    width = len(table.headers) - 1
    unknown = ['unknown'] * max(width, 0)
    if not words or not valid_box(table.bbox) or width < 1 or table.source_rotation or page.reading_rotation:
        return unknown
    lines = source_lines(page, page.text, str.strip, words=words)
    compact = lambda text: ''.join(normalize_quote(text).split())
    year_headers = {compact(raw) for raw in table.raw_header_lines
                    if len(re.findall(_YEAR, raw)) >= 2}
    candidates = [i for i, line in enumerate(lines) if compact(line.text) in year_headers
                  and line.bottom is not None and line.bottom < table.bbox[1]]
    if not candidates:
        return unknown
    year_index = max(candidates, key=lambda i: lines[i].bottom)
    annotations = [line for line in lines[year_index + 1:]
                   if line.top is not None and line.top < table.bbox[1]
                   and normalize_quote(line.text) in labels]
    from adaptive_document_agent.extraction.period_header_geometry import geometric_periods
    periods = geometric_periods(lines[max(0, year_index - 5):year_index], lines[year_index], width)
    if periods is None:
        return unknown
    statuses = geometric_audit_statuses(annotations, lines[year_index], width)
    header_text = ' '.join(table.raw_header_lines)
    for i, actual in enumerate(periods):
        stored = table.column_periods[i + 1] if i + 1 < len(table.column_periods) else ''
        stored = re.sub(r'\s+', '', stored or '').upper()
        equivalent = {actual.upper()}
        interim = re.fullmatch(r'6M(\d{4})', actual, re.I)
        if interim:
            if re.search(r'June\s*30', header_text, re.I):
                equivalent.update((f'1H{interim[1]}', f'H1{interim[1]}'))
            elif re.search(r'December\s*31', header_text, re.I):
                equivalent.update((f'2H{interim[1]}', f'H2{interim[1]}'))
        if stored not in equivalent:
            statuses[i] = 'unknown'
    return statuses


def source_audit_scope(item, result):
    """Expose existing source column bindings only for complete cited rows.

    A visible label elsewhere in a header never qualifies an unmarked column.
    Unknown remains unknown. This is evidence context, not an acceptance verdict.
    """
    if result is None:
        return []
    pages = {page.page_number: page for page in result.document.pages}
    passages = continuous_quote_passages(item.evidence, {n: p.text for n, p in pages.items()})
    quoted = {}
    for passage in passages:
        if passage.page in pages and normalize_quote(passage.text) in normalize_quote(pages[passage.page].text):
            quoted.setdefault(passage.page, []).append(normalize_quote(passage.text))
    inventory = []
    for number, quotes in quoted.items():
        page = pages[number]
        for table in page.tables:
            rows = []
            for row in table.rows:
                cells = [str(c).strip() for c in row.cells if c and str(c).strip()]
                if (row.alignment_status == 'resolved' and cells
                        and any(parse_number(c) is not None for c in cells)
                        and any(_quoted_complete_row(cells, q) for q in quotes)):
                    rows.append(cells[0])
            if not rows:
                continue
            labels = []
            for raw in table.raw_header_lines:
                located = _located_header(raw, page.text)
                if located and _STATUS.search(located) and any(located in q for q in quotes):
                    labels.append(located)
            available = {m[0].casefold() for label in labels for m in _STATUS.finditer(label)}
            geometric = _geometric_statuses(page, table, labels)
            duration_dates = set()
            _header_dates(table, page.text, duration_bindings=duration_dates)
            columns = []
            for index, period in enumerate(table.column_periods):
                if not period:
                    continue
                status = table.column_audit_statuses[index] if index < len(table.column_audit_statuses) else 'unknown'
                status = status if (status in available and 0 <= index - 1 < len(geometric)
                                    and geometric[index - 1] == status) else 'unknown'
                aliases = {period}
                match = re.fullmatch(r'(\d+)M((?:19|20)\d{2})', period, re.I)
                half = re.fullmatch(r'(?:1H|H1)((?:19|20)\d{2})', period, re.I)
                duration = (int(match[1]), match[2]) if match else (6, half[1]) if half else None
                if duration:
                    for months, month, day, year in duration_dates:
                        if (months, year) == duration:
                            aliases.add(date(int(year), [m.casefold() for m in _MONTHS].index(month) + 1,
                                             int(day)).isoformat())
                columns.append({'column': index, 'period': period, 'status': status,
                                'date_aliases': sorted(aliases - {period})})
            inventory.append({'page': number, 'table_id': table.table_id, 'row_labels': rows,
                              'columns': columns, 'literal_audit_header_lines': labels,
                              'binding_basis': 'complete_quoted_row_and_verified_column_geometry',
                              'source_table_confidence': table.confidence})
    return inventory


def _period_keys(match, columns):
    value = match[0]
    if match['flow']:
        duration = re.match(rf'({_DURATION})\s+months?', value, re.I)
        months, year = month_count(duration[1]), value[-4:]
        keys = {f'{months}M{year}'}
        if months == 6 and re.search(r'June\s+30,?\s+\d{4}$', value, re.I):
            keys.update((f'1H{year}', f'H1{year}'))
        elif months == 6 and re.search(r'December\s+31,?\s+\d{4}$', value, re.I):
            keys.update((f'2H{year}', f'H2{year}'))
        return keys
    if match['label']:
        label = re.sub(r'\s+', '', value).upper()
        half = re.fullmatch(r'(?:1H|H1)(\d{4})', label)
        if half:
            keys = {label, f'1H{half[1]}', f'H1{half[1]}'}
            # A six-month duration is not inherently the first half. Only
            # a source-bound June closing date can lend this calendar alias.
            if any(re.sub(r'\s+', '', c['period']).upper() == f'6M{half[1]}'
                   and f'{half[1]}-06-30' in c['date_aliases'] for c in columns):
                keys.add(f'6M{half[1]}')
            return keys
        six = re.fullmatch(r'6M(\d{4})', label)
        if six:
            return {label, f'1H{six[1]}', f'H1{six[1]}'}
        second = re.fullmatch(r'(?:2H|H2)(\d{4})', label)
        return {label, f'2H{second[1]}', f'H2{second[1]}'} if second else {label}
    if match['date']:
        parts = re.fullmatch(rf'({_MONTH})\s+(\d{{1,2}}),?\s+({_YEAR})', value, re.I)
        try:
            key = date(int(parts[3]), [m.casefold() for m in _MONTHS].index(parts[1].casefold()) + 1,
                       int(parts[2])).isoformat()
        except ValueError:
            return set()
    elif match['iso']:
        key = value
    else:
        return {re.sub(r'\s+', '', c['period']).upper() for c in columns if value in c['period']}
    return {re.sub(r'\s+', '', c['period']).upper() for c in columns
            if key == c['period'] or key in c['date_aliases']}


def _assertions(text, columns):
    assertions = []
    periods = list(_PERIOD.finditer(text))
    for status in _STATUS.finditer(text):
        for period in periods:
            if status.end() <= period.start():
                between = text[status.end():period.start()]
                attached = re.fullmatch(r'\s*(?:(?:figures|data|results)\s+(?:for|in)\s+)?(?:the\s+)?', between, re.I)
            elif period.end() <= status.start():
                between = text[period.end():status.start()]
                attached = re.fullmatch(r'\s*[,()]?\s*(?:(?:figures|data|results)\s+(?:are|were)\s+)?', between, re.I)
            else:
                continue
            if not attached:
                continue
            keys = _period_keys(period, columns)
            assertions.append((status, period, keys))
    return assertions


def audit_status_errors(item, result, *, inventory=None):
    """Reject explicit date/status assertions contradicted by their bound grid.

    Only immediate temporal qualifiers enter this deterministic check. General
    narrative about auditors, forecasts or assurance stays with semantic review.
    Explicit, independently quoted source prose can qualify its own period.
    """
    inventory = source_audit_scope(item, result) if inventory is None else inventory
    columns = [column for table in inventory for column in table['columns']]
    if not columns:
        return []
    prose = set()
    pages = {p.page_number: p.text for p in result.document.pages}
    for quote in item.evidence:
        if normalize_quote(quote.text) not in normalize_quote(pages.get(quote.page, '')):
            continue
        # Permit only a complete affirmative assurance sentence. Joining
        # ordinary PDF line wraps cannot turn a header, denial, conditional or
        # uncertainty statement into positive assurance evidence.
        for sentence in re.split(r'(?<!\d)[.!?](?!\d)\s*', ' '.join(quote.text.split())):
            form = re.fullmatch(r'(?:The\s+)?(?P<subject>.+?)\s+(?:is|are|was|were)\s+'
                                r'(?P<status>unaudited|audited)', sentence, re.I)
            if not form:
                continue
            subject = re.sub(r'^(?:(?:consolidated|financial)\s+)*(?:figures|data|results|statements|information)\s+for\s+',
                             '', form['subject'], flags=re.I)
            subject = re.sub(r'\s+(?:(?:consolidated|financial)\s+)*(?:figures|data|results|statements|information)$',
                             '', subject, flags=re.I)
            period = _PERIOD.fullmatch(subject)
            if period and not period['year']:
                prose.update((form['status'].casefold(), key) for key in _period_keys(period, columns))
    errors = []
    for status, period, keys in _assertions(item.text, columns):
        applicable = {re.sub(r'\s+', '', c['period']).upper() for c in columns} & keys
        if applicable and all((status[0].casefold(), key) in prose for key in applicable):
            continue
        statuses = {c['status'] for c in columns if re.sub(r'\s+', '', c['period']).upper() in keys}
        if not keys or statuses != {status[0].casefold()}:
            errors.append(f"Audit status '{status[0]}' for '{period[0]}' lacks unambiguous "
                          'source column support; unmarked columns remain unknown, not audited or unaudited.')
    return list(dict.fromkeys(errors))
