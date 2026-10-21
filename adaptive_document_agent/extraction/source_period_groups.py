"""Bind duration/date superheaders only to literal or proved spanned columns."""
import re

from .period_header_geometry import MONTH_DURATION, month_count
from adaptive_document_agent.document_model.period_semantic_validator import format_period_label

REFERENCE_HEADER = re.compile(r'(?i)^(?:notes?|references?|refs?\.?|附注|附註)$')


def qualified_source_periods(header, periods):
    descriptors = []
    for row in header:
        for column, value in enumerate(row[1:], 1):
            text = str(value or '').strip()
            if re.match(r'(?i)^(?:for\s+the\s+)?years?\s+ended\b', text):
                descriptors.append((column, 'FY', text))
            elif match := re.match(r'(?i)^(?:for\s+the\s+)?' + MONTH_DURATION + r'\s*ended\b', text):
                descriptors.append((column, f'{month_count(match.group(1))}M', text))
            elif re.match(r'(?i)^as\s+(?:of|at)\b', text):
                descriptors.append((column, 'snapshot', text))
    if not descriptors:
        return periods, None
    qualified = dict(periods)
    for column, year in periods.items():
        if not re.fullmatch(r'(?:19|20)\d{2}', year):
            continue
        labels = set()
        for owner, basis, text in descriptors:
            if owner != column:
                continue
            if basis == 'snapshot':
                label = format_period_label(f'{text} {year}', is_balance_sheet=True)
                if not re.fullmatch(r'\d{1,2} [A-Za-z]{3} (?:19|20)\d{2}', label):
                    continue
            else:
                label = basis + year
            labels.add(label)
        if len(labels) != 1:
            return {}, 'a period superheader has no unique aligned duration/date for each year column'
        qualified[column] = labels.pop()
    return qualified, None
