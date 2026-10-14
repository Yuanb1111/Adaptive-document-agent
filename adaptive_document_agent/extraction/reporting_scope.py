"""Retain explicit reporting-entity labels from source table headings."""
import re

_SCOPE = re.compile(r'(?i)(?<!\w)(?:the\s+)?(?P<label>group|company|consolidated|standalone)(?!\w)|集团|集團|本公司|母公司|合并|合併')


def literal_reporting_scope(text):
    matches = list(_SCOPE.finditer(text or ''))
    if len(matches) != 1:
        return None
    # Company names or body sentences are not reporting-basis declarations.
    remaining = _SCOPE.sub('', text)
    remaining = re.sub(r'(?i)(?:19|20)\d{2}|FY|as\s+(?:at|of)|year\s+ended|RMB|USD|HKD|CNY|in\s+thousands|[\d\s,:()/%\-]+', '', remaining)
    if remaining.strip():
        return None
    return matches[0].group().strip()


def table_reporting_scope(table, row_index, column, section=None):
    # The nearest explicit column or row heading wins over broader table scope.
    candidates = [table.headers[column] if column is not None and column < len(table.headers) else '']
    if column is not None:
        # Only literal merged spans authorize inheriting a parent header;
        # blank neighboring columns cannot establish an entity on their own.
        for row, start, end in table.raw_header_spans:
            if start <= column <= end and 0 <= row < len(table.raw_header_cells):
                cells = table.raw_header_cells[row]
                if start < len(cells):
                    candidates.append(cells[start])
        candidates.extend(cells[column] for cells in reversed(table.raw_header_cells) if column < len(cells))
    if 0 <= row_index < len(table.rows) and table.rows[row_index].cells:
        candidates.append(table.rows[row_index].cells[0])
    candidates.append(section)
    candidates.extend([table.table_title, table.context_label])
    for text in candidates:
        scope = literal_reporting_scope(text)
        if scope:
            return scope
    for text in (table.table_title, table.context_label):
        matches = list(_SCOPE.finditer(text or ''))
        if len(matches) == 1 and matches[0].group().casefold() in {'consolidated', 'standalone', '合并', '合併', '母公司'}:
            return matches[0].group()
    return None
