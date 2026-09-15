"""Growth calculations."""


def growth_rate(start: float, end: float) -> float:
    from .comparison import percentage_change

    return percentage_change(start, end)


def cagr(start: float, end: float, periods: int) -> float:
    if start <= 0 or end < 0 or periods <= 0:
        raise ValueError("CAGR requires positive start, non-negative end, and positive periods.")
    return float(((end / start) ** (1 / periods) - 1) * 100.0)

