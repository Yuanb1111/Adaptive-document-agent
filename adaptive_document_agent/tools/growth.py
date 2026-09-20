"""Growth calculations."""


def growth_rate(start: float, end: float, *, is_expense: bool = False) -> float:
    from .comparison import percentage_change

    return percentage_change(start, end, is_expense=is_expense)


def cagr(start: float, end: float, periods: int, *, is_expense: bool = False) -> float:
    if is_expense and start < 0 and end <= 0:
        s_mag = abs(start)
        e_mag = abs(end)
        if s_mag <= 0 or e_mag < 0 or periods <= 0:
            raise ValueError("CAGR requires positive start, non-negative end, and positive periods.")
        return float(((e_mag / s_mag) ** (1 / periods) - 1) * 100.0)

    if start <= 0 or end < 0 or periods <= 0:
        raise ValueError("CAGR requires positive start, non-negative end, and positive periods.")
    return float(((end / start) ** (1 / periods) - 1) * 100.0)

