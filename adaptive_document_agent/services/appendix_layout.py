"""Balance contiguous appendix rows without changing their evidence or periods."""


def paginate_themes(themes: list[tuple[str, dict]], *, capacity: float = 10,
                    row_cost=None, heading_cost=None) -> list[list[tuple[str, dict]]]:
    """Minimize pages, then unused space, counting each repeated section header.

    Call separately for each compatible period group. Topics keep their order;
    a topic may continue onto the next page instead of leaving a sparse tail.
    """
    rows = [(theme, key, entry) for theme, entries in themes for key, entry in entries.items()]
    row_cost = row_cost or (lambda entry: 1)
    heading_cost = heading_cost or (lambda theme: 1)
    best = [(0, 0, [])] + [None] * len(rows)
    for end in range(1, len(rows) + 1):
        used = 0
        for start in range(end - 1, -1, -1):
            if start == end - 1 or rows[start][0] != rows[start + 1][0]:
                used += heading_cost(rows[start][0])
            used += row_cost(rows[start][2])
            if used > capacity:
                break
            previous = best[start]
            if previous is None:
                continue
            candidate = (previous[0] + 1, previous[1] + (capacity - used) ** 2,
                         [*previous[2], (start, end)])
            if best[end] is None or candidate[:2] < best[end][:2]:
                best[end] = candidate
    if rows and best[-1] is None:
        raise ValueError("Appendix capacity cannot fit a metric and its heading")
    pages = []
    for start, end in best[-1][2]:
        bundle = []
        for theme, key, entry in rows[start:end]:
            if not bundle or bundle[-1][0] != theme:
                bundle.append((theme, {}))
            bundle[-1][1][key] = entry
        pages.append(bundle)
    return pages
