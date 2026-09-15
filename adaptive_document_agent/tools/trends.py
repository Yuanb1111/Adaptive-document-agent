"""Ordered trend functions."""


def moving_average(values: list[float], window: int = 3) -> list[float | None]:
    if window <= 0:
        raise ValueError("Moving-average window must be positive.")
    return [None if index + 1 < window else float(sum(values[index + 1 - window : index + 1]) / window) for index in range(len(values))]


def linear_trend(values: list[float], x: list[float] | None = None) -> dict[str, float | str]:
    if len(values) < 3:
        raise ValueError("Linear trend requires at least three ordered observations.")
    x = x or [float(index) for index in range(len(values))]
    if len(x) != len(values):
        raise ValueError("Trend x and y lengths must match.")
    x_mean = sum(x) / len(x)
    y_mean = sum(values) / len(values)
    denominator = sum((item - x_mean) ** 2 for item in x)
    if denominator == 0:
        raise ValueError("Trend x values must vary.")
    slope = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, values, strict=True)) / denominator
    intercept = y_mean - slope * x_mean
    changes = [right - left for left, right in zip(values, values[1:])]
    nonzero_signs = [1 if change > 0 else -1 for change in changes if change != 0]
    turning_points = sum(left != right for left, right in zip(nonzero_signs, nonzero_signs[1:]))
    monotonic = not nonzero_signs or all(sign == nonzero_signs[0] for sign in nonzero_signs)
    if monotonic:
        direction = "increasing" if slope > 0 else "decreasing" if slope < 0 else "flat"
    else:
        direction = "mixed"
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "direction": direction,
        "turning_points": float(turning_points),
        "start_value": float(values[0]),
        "end_value": float(values[-1]),
    }
