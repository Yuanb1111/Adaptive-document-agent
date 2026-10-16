"""Prove literal layout lines without treating extracted reading order as geometry."""
import math
import re


def _text(value):
    return ' '.join(value.split())


def _geometry_rows(page):
    rows = []
    for block in page.text_blocks:
        candidates = block.get('lines') or ([block] if len(str(block.get('text', '')).splitlines()) == 1 else [])
        for line in candidates:
            if not isinstance(line, dict):
                continue
            text, box = _text(str(line.get('text', ''))), line.get('bbox')
            if not text or not isinstance(box, (tuple, list)) or len(box) != 4:
                continue
            try:
                box = tuple(float(value) for value in box)
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(value) for value in box) and box[2] > box[0] and box[3] > box[1]:
                rows.append((text, box))
    return rows


def _label_like(text):
    # Repetition or an edge position must not hide a repeated disclaimer or
    # sentence. Ambiguous prose remains content for the reading model/editor.
    if len(text) > 100 or len(text.split()) > 10 or re.search(r'[.!?;。！？；]', text):
        return False
    cased = any(character.lower() != character.upper() for character in text)
    return not cased or text.isupper() or text.istitle()


def _margin_matches(text, page):
    rows = _geometry_rows(page)
    matches = [box for value, box in rows if value == text]
    if not matches:
        return []
    top, bottom = min(box[1] for _, box in rows), max(box[3] for _, box in rows)
    margins = []
    for box in matches:
        height = box[3] - box[1]
        # A tall rotated table column is not a compact running header merely
        # because its bounding rectangle reaches the top of the page.
        if height > 30:
            return []
        band = 'top' if box[1] <= top + max(16, height * 2) else (
            'bottom' if box[3] >= bottom - max(16, height * 2) else '')
        if not band:
            return []  # An identical body occurrence leaves ownership unclear.
        margins.append((band, box))
    return margins


def _running_label(text, page, pages):
    if not _label_like(text):
        return None
    matches = _margin_matches(text, page)
    if matches:
        band, box = matches[0]
        peers = []
        for candidate in pages:
            aligned = _margin_matches(text, candidate)
            if aligned and all(other_band == band and abs(other[1] - box[1]) <= 16
                               for other_band, other in aligned):
                peers.append(candidate.page_number)
        if len(set(peers)) >= 2:
            return {'basis': 'repeated_source_margin', 'bbox': list(box), 'peer_pages': sorted(set(peers))}
    # Older retained documents may lack geometry. Use this conservative
    # textual proof only when geometry cannot contradict the edge location.
    if _geometry_rows(page):
        return None
    def edges(candidate):
        lines = [_text(line) for line in candidate.text.splitlines() if line.strip()]
        return {lines[0], lines[-1]} if lines else set()
    peers = [candidate.page_number for candidate in pages if text in edges(candidate)]
    if text in edges(page) and len(set(peers)) >= 2:
        return {'basis': 'repeated_extracted_edge', 'peer_pages': sorted(set(peers))}
    return None


def layout_line_evidence(source: str, page_number: int, result) -> list[dict]:
    """Prove every grouped layout line; retain wording and model roles unchanged."""
    page = next((p for p in result.document.pages if p.page_number == page_number), None)
    source_lines = source.splitlines() or ['']
    if page is None:
        return [{'line': i, 'text': line, 'proved': not line.strip(), 'basis': 'unknown_source_page'}
                for i, line in enumerate(source_lines, 1)]
    visible = [_text(line) for line in page.text.splitlines() if line.strip()]
    tokens = r'(?:as|at|of|for|the|year|years|ended|ending|six|three|months?|December|June|RMB|CNY|USD|HKD|in|thousands?|millions?|billions?|unaudited|audited)'
    whole = _text(source)
    remainder = re.sub(rf'(?i)\b{tokens}\b|[\d\s,;:()/%\-]+', '', whole)
    # A year somewhere in an otherwise numeric body is not proof that the
    # remaining numbers are headers. Permit explicit calendar-day notation,
    # while ordinary table amounts still need retained table-header evidence.
    month_named = bool(re.search(r'(?i)\b(?:December|June)\b', whole))
    calendar_numbers = all(re.fullmatch(r'(?:19|20)\d{2}', number)
                           or month_named and 1 <= int(number) <= 31
                           for number in re.findall(r'\d+', whole))
    calendar_group = (not remainder and calendar_numbers
                      and bool(re.search(r'(?i)\b(?:19|20)\d{2}\b', whole)))
    headers = {_text(line) for table in page.tables + page.raw_tables for line in table.raw_header_lines
               if line.strip()}
    records = []
    for number, raw in enumerate(source_lines, 1):
        text, proof = _text(raw), None
        if not text:
            proof = {'basis': 'blank'}
        elif visible and text == visible[-1] and (
                re.fullmatch(r'[^\w]+(?:\d+|[ivxlcdm]+)[^\w]+', text, re.I)
                or re.fullmatch(r'page\s+\d+', text, re.I)):
            proof = {'basis': 'literal_terminal_page_marker'}
        elif calendar_group:
            proof = {'basis': 'literal_calendar_unit_header'}
        elif text in headers:
            proof = {'basis': 'retained_source_table_header'}
        else:
            proof = _running_label(text, page, result.document.pages)
        records.append({'line': number, 'text': raw, 'proved': proof is not None,
                        **(proof or {'basis': 'no_mechanical_source_evidence'})})
    return records


def mechanical_layout(source: str, page_number: int, result) -> bool:
    return all(line['proved'] for line in layout_line_evidence(source, page_number, result))
