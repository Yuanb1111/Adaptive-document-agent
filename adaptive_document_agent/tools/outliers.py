"""Conservative outlier detection."""

import statistics


def iqr_outliers(values: list[float]) -> list[int]:
    if len(values) < 5:
        raise ValueError("IQR outlier detection requires at least five observations.")
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    q1, q3 = quartiles[0], quartiles[2]
    spread = q3 - q1
    lower, upper = q1 - 1.5 * spread, q3 + 1.5 * spread
    return [index for index, value in enumerate(values) if value < lower or value > upper]


def zscore_outliers(values: list[float], threshold: float = 3.0) -> list[int]:
    if len(values) < 5:
        raise ValueError("Z-score outlier detection requires at least five observations.")
    deviation = statistics.pstdev(values)
    if deviation == 0:
        return []
    average = statistics.fmean(values)
    return [index for index, value in enumerate(values) if abs((value - average) / deviation) > threshold]

