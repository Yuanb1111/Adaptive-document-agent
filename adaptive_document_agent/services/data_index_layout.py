"""Measure source-index columns and balance unavoidable continuation pages."""
from functools import lru_cache

from .text_capacity import wrap_copy


def fit_columns(values, width):
    candidates = []
    for topic in range(30, 53, 2):
        for units in range(12, 21, 2):
            fractions = (topic / 100, units / 100, (84 - topic - units) / 100, .16)
            if fractions[2] < .18:
                continue
            widths = [width * fraction for fraction in fractions]
            rows = [(row, max(.44, max(len(wrap_copy(v, w - .16, 12)) * .22 + .12
                        for v, w in zip(row, widths)))) for row in values]
            score = (round(sum(h for _, h in rows), 6),
                     sum(abs(a - b) for a, b in zip(fractions, (.30, .13, .39, .18))))
            candidates.append((score, widths, rows))
    _, widths, rows = min(candidates, key=lambda choice: choice[0])
    return widths, rows


def balanced_pages(rows, capacity, gap=.10):
    """Minimize page count, then balance filled height while preserving order."""
    @lru_cache(None)
    def partition(start):
        if start == len(rows):
            return 0, 0.0, ()
        used, choices = 0.0, []
        for end in range(start + 1, len(rows) + 1):
            used += rows[end - 1][1] + (gap if end > start + 1 else 0)
            if used > capacity + 1e-8:
                break
            tail = partition(end)
            if tail is not None:
                choices.append((tail[0] + 1, tail[1] + used ** 2, (end, *tail[2])))
        return min(choices) if choices else None
    choice = partition(0)
    if choice is None:
        raise ValueError('A source-index entry exceeds readable page capacity; review its planned scope')
    pages, start = [], 0
    for end in choice[2]:
        pages.append(rows[start:end])
        start = end
    return pages
