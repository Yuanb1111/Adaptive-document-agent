"""Change and comparison functions."""


def absolute_change(start: float, end: float) -> float:
    return float(end - start)


def percentage_change(start: float, end: float) -> float:
    if start == 0:
        raise ValueError("Percentage change is undefined when the starting value is zero.")
    return float((end - start) / abs(start) * 100.0)


def compare_periods(labels: list[str], values: list[float]) -> list[dict[str, float | str]]:
    if len(labels) != len(values):
        raise ValueError("Labels and values must have the same length.")
    return [{"period": label, "value": value} for label, value in zip(labels, values, strict=True)]


def compare_categories(labels: list[str], values: list[float]) -> list[dict[str, float | str]]:
    if len(labels) != len(values):
        raise ValueError("Labels and values must have the same length.")
    return [{"category": label, "value": value} for label, value in zip(labels, values, strict=True)]

