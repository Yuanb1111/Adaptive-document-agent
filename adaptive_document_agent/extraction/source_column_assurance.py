"""Retain isolated literal assurance markers on checked original header cells."""
import re


def literal_column_statuses(table, periods):
    """Never propagate a marker across a group, reference column or blank cell."""
    statuses = ['unknown'] * len(periods)
    if table.source_layout_status != 'checked' or not table.raw_header_cells:
        return statuses
    for row_number, row in enumerate(table.raw_header_cells):
        for column, cell in enumerate(row):
            if column >= len(periods) or not periods[column]:
                continue
            match = re.fullmatch(r'\s*\(?\s*(unaudited|audited)\s*\)?\s*', str(cell or ''), re.I)
            if not match or any(r == row_number and a <= column <= b and a != b
                                for r, a, b in table.raw_header_spans):
                continue
            status = match[1].lower()
            if statuses[column] not in {'unknown', status}:
                return ['unknown'] * len(periods)  # Conflicting marks need independent review.
            statuses[column] = status
    return statuses
