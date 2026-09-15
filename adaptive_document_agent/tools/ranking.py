"""Category ranking."""


def rank_values(labels: list[str], values: list[float], *, descending: bool = True) -> list[dict[str, float | int | str]]:
    if len(labels) != len(values):
        raise ValueError("Labels and values must have the same length.")
    ordered = sorted(zip(labels, values, strict=True), key=lambda item: item[1], reverse=descending)
    return [{"rank": rank, "label": label, "value": float(value)} for rank, (label, value) in enumerate(ordered, start=1)]


def top_n(labels: list[str], values: list[float], n: int = 5) -> list[dict[str, float | int | str]]:
    return rank_values(labels, values)[: max(0, n)]


def bottom_n(labels: list[str], values: list[float], n: int = 5) -> list[dict[str, float | int | str]]:
    return rank_values(labels, values, descending=False)[: max(0, n)]

