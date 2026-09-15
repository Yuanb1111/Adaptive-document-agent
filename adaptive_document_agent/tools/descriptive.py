"""Descriptive statistics."""

import statistics


def sum_values(values: list[float]) -> float:
    return float(sum(values))


def mean(values: list[float]) -> float:
    return float(statistics.fmean(values))


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def minimum(values: list[float]) -> float:
    return float(min(values))


def maximum(values: list[float]) -> float:
    return float(max(values))


def standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        raise ValueError("Standard deviation requires at least two observations.")
    return float(statistics.stdev(values))

