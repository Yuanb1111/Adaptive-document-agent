"""Balance contiguous appendix rows without changing their evidence or periods."""


def paginate_themes(themes: list[tuple[str, dict]], *, capacity: float = 10,
                    row_cost=None, heading_cost=None) -> list[list[tuple[str, dict]]]:
    """Keep fitting topics intact, then minimize pages and unused space.

    Call separately for each compatible period group. Topics keep their order;
    a topic larger than the page capacity can continue without dropping rows.
    """
    rows = [(theme, key, entry) for theme, entries in themes for key, entry in entries.items()]
    row_cost = row_cost or (lambda entry: 1)
    heading_cost = heading_cost or (lambda theme: 1)
    # A source composition should remain a complete reader unit even if moving
    # it to the next page creates some whitespace on the preceding page.
    topic_costs = {theme: heading_cost(theme) + sum(row_cost(entry) for entry in entries.values())
                   for theme, entries in themes}
    best = [(0, 0, 0, [])] + [None] * len(rows)
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
            splits = int(start > 0 and rows[start - 1][0] == rows[start][0]
                         and topic_costs[rows[start][0]] <= capacity)
            candidate = (previous[0] + splits, previous[1] + 1,
                         previous[2] + (capacity - used) ** 2,
                         [*previous[3], (start, end)])
            if best[end] is None or candidate[:3] < best[end][:3]:
                best[end] = candidate
    if rows and best[-1] is None:
        raise ValueError("Appendix capacity cannot fit a metric and its heading")
    pages = []
    for start, end in best[-1][3]:
        bundle = []
        for theme, key, entry in rows[start:end]:
            if not bundle or bundle[-1][0] != theme:
                bundle.append((theme, {}))
            bundle[-1][1][key] = entry
        pages.append(bundle)
    return pages
