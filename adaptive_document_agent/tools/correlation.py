"""Correlation with explicit minimum sample sizes."""


def pearson_correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 5:
        raise ValueError("Pearson correlation requires at least five paired observations.")
    try:
        from scipy.stats import pearsonr

        return float(pearsonr(left, right).statistic)
    except ImportError:
        return _pearson(left, right)


def spearman_correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 5:
        raise ValueError("Spearman correlation requires at least five paired observations.")
    try:
        from scipy.stats import spearmanr

        return float(spearmanr(left, right).statistic)
    except ImportError:
        return _pearson(_ranks(left), _ranks(right))


def _pearson(left: list[float], right: list[float]) -> float:
    l_mean, r_mean = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((a - l_mean) * (b - r_mean) for a, b in zip(left, right, strict=True))
    denominator = (sum((a - l_mean) ** 2 for a in left) * sum((b - r_mean) ** 2 for b in right)) ** 0.5
    if denominator == 0:
        raise ValueError("Correlation is undefined for constant values.")
    return float(numerator / denominator)


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        rank = (index + end) / 2 + 1
        for position in range(index, end + 1):
            ranks[ordered[position][0]] = rank
        index = end + 1
    return ranks

