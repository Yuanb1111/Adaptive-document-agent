"""Retain physical source tables independently of analytical series selection."""

from collections import Counter


def _cells(table):
    return Counter(str(cell).strip() for row in table.raw_cells for cell in row if cell)


def retain_source_tables(tables):
    """Remove only evidenced duplicates/subsets, never low analytical scores."""
    retained = []
    for table in tables:
        cells = _cells(table)
        duplicate = None
        for index, prior in enumerate(retained):
            previous = _cells(prior)
            if table.table_id == prior.table_id:
                duplicate = index
                break
            if table.bbox and prior.bbox:
                a, b = table.bbox, prior.bbox
                intersects = min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])
                if intersects and cells and previous and (cells <= previous or previous <= cells):
                    duplicate = index
                    break
        if duplicate is None:
            retained.append(table)
        elif (_cells(retained[duplicate]) < cells or
              (cells == _cells(retained[duplicate]) and len(table.raw_header_lines) > len(retained[duplicate].raw_header_lines))):
            retained[duplicate] = table
    return retained
