"""Physical chart capacity from plotted series and display labels, never topic."""


def legend_rows(categories, width, font):
    available = max(1, width * 72 - 24)
    rows, occupied = 1, 0
    for category in categories:
        needed = len(category) * font * .52 + 18
        if occupied and occupied + needed > available:
            rows, occupied = rows + 1, 0
        occupied += needed
    return rows


def composition_plot_height(bounds, categories, *, compact):
    font = 10 if compact else 11
    return bounds[3] - (30 + legend_rows(categories, bounds[2], font) * font * 1.5) / 72


def chart_space_requirements(plan, observations, totals):
    """Minimum width and inner plot height; outer boxes also contain axes/legend."""
    from .composition_data import composition_data, uses_composition_data
    if not uses_composition_data(plan):
        return 2.4, 1.25, []
    matrix = composition_data(plan, observations, totals)
    categories = matrix.categories
    width = max(3.2, min(5.6, 1.8 + len(categories) * .45 + max(map(len, categories), default=0) * .025))
    height = max(1.6, min(2.4, .6 + len(categories) * .35))
    return width, height, categories
