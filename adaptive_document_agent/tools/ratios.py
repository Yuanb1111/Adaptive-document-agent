"""Ratios and contribution calculations."""


def ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        raise ValueError("Ratio denominator cannot be zero.")
    return float(numerator / denominator)


def percentage_of_total(value: float, total: float) -> float:
    return ratio(value, total) * 100.0


def contribution_share(values: list[float]) -> list[float]:
    total = sum(values)
    if total == 0:
        raise ValueError("Contribution share is undefined for a zero total.")
    return [float(value / total * 100.0) for value in values]

