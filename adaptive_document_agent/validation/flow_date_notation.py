"""Check complete stated flow dates against selected source cells before normalizing spellings."""
from datetime import date
import re

from adaptive_document_agent.extraction.period_header_geometry import MONTH_COUNTS, month_count

_MONTHS = 'January February March April May June July August September October November December'.split()
_YEAR = r'(?:19|20)\d{2}'
_FLOW_DATE = re.compile(
    rf'\b(?P<duration>{"|".join(MONTH_COUNTS)}|1[0-2]|[1-9])\s+months?\s+ended\s+'
    rf'(?P<month>{"|".join(_MONTHS)})\s+(?P<day>\d{{1,2}}),?\s+'
    rf'(?P<years>{_YEAR}(?:,\s*{_YEAR})*(?:,?\s+and\s+{_YEAR})?)(?![\w-])', re.I)


def normalize_bound_flow_dates(text, members, result):
    """Only the numeric-check copy changes. Unsupported phrases retain all original tokens."""
    if result is None or not _FLOW_DATE.search(text):
        return text
    from adaptive_document_agent.agent.brief_period_geometry import table_flow_closings
    pages = {page.page_number: page for page in result.document.pages}
    dates = {}

    def supports(item, months, closing):
        row, col = item.row_id, item.column_id
        if (row is None or col is None or row < 0 or col < 1
                or item.period_type not in {'generic', 'interim_flow', 'interim_period'}
                or item.period_basis.upper() not in {'', 'GENERIC', f'{months}M'}
                or (item.period_end and item.period_end != closing)):
            return False
        owned_closings = set()
        for evidence in item.evidence:
            page = pages.get(evidence.page)
            if page is None or not evidence.table_id or evidence.table_id != item.effective_table_id:
                continue
            tables = [t for t in page.tables if t.table_id == evidence.table_id and t.page == evidence.page]
            if len(tables) != 1:
                return False
            table = tables[0]
            if row >= len(table.rows) or col >= len(table.column_periods) or col >= len(table.headers):
                continue
            source = table.rows[row]
            if (source.alignment_status != 'resolved' or source.page != evidence.page or col >= len(source.cells)
                    or source.cells[0] != evidence.row_label or source.cells[col] != item.raw_value
                    or (evidence.column_label and evidence.column_label != table.headers[col])
                    or table.column_periods[col] != item.period):
                continue
            key = (evidence.page, evidence.table_id)
            if key not in dates:
                dates[key] = table_flow_closings(page, table)
            owned_closings.update(day for duration, day in dates[key]
                                  if duration == months and day[:4] == closing[:4])
        return owned_closings == {closing}

    def replace(match):
        months = month_count(match['duration'])
        month = _MONTHS.index(match['month'].capitalize()) + 1
        periods = []
        for year in re.findall(_YEAR, match['years']):
            try:
                closing = date(int(year), month, int(match['day'])).isoformat()
            except ValueError:
                return match[0]
            label = f'{months}M{year}'
            owners = [item for item in members if item.period == label]
            if not owners or not all(supports(item, months, closing) for item in owners):
                return match[0]
            periods.append(label)
        return ' and '.join(periods)

    return _FLOW_DATE.sub(replace, text)
