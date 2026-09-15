"""Metadata-rich registry decoupling planner and calculations."""

from dataclasses import dataclass
from typing import Any, Callable

from . import comparison, correlation, descriptive, growth, outliers, ranking, ratios, trends


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    function: Callable[..., Any]
    description: str
    minimum_observations: int
    input_shape: str
    supported_units: str = "compatible"
    output_format: str = "number"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        if name not in self._tools:
            raise KeyError(f"Unknown analysis tool: {name}")
        return self._tools[name]

    def execute(self, name: str, **kwargs: Any) -> Any:
        return self.get(name).function(**kwargs)

    def definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    specs = [
        ("sum_values", descriptive.sum_values, 1, "values"),
        ("mean", descriptive.mean, 1, "values"),
        ("median", descriptive.median, 1, "values"),
        ("minimum", descriptive.minimum, 1, "values"),
        ("maximum", descriptive.maximum, 1, "values"),
        ("standard_deviation", descriptive.standard_deviation, 2, "values"),
        ("absolute_change", comparison.absolute_change, 2, "start,end"),
        ("percentage_change", comparison.percentage_change, 2, "start,end"),
        ("growth_rate", growth.growth_rate, 2, "start,end"),
        ("cagr", growth.cagr, 3, "start,end,periods"),
        ("ratio", ratios.ratio, 2, "numerator,denominator"),
        ("percentage_of_total", ratios.percentage_of_total, 2, "value,total"),
        ("contribution_share", ratios.contribution_share, 2, "values", "compatible", "series"),
        ("rank_values", ranking.rank_values, 2, "labels,values", "compatible", "table"),
        ("top_n", ranking.top_n, 2, "labels,values", "compatible", "table"),
        ("bottom_n", ranking.bottom_n, 2, "labels,values", "compatible", "table"),
        ("compare_periods", comparison.compare_periods, 2, "labels,values", "compatible", "table"),
        ("compare_categories", comparison.compare_categories, 2, "labels,values", "compatible", "table"),
        ("moving_average", trends.moving_average, 3, "values", "compatible", "series"),
        ("linear_trend", trends.linear_trend, 3, "values", "compatible", "object"),
        ("iqr_outliers", outliers.iqr_outliers, 5, "values", "compatible", "indices"),
        ("zscore_outliers", outliers.zscore_outliers, 5, "values", "compatible", "indices"),
        ("pearson_correlation", correlation.pearson_correlation, 5, "left,right", "any", "number"),
        ("spearman_correlation", correlation.spearman_correlation, 5, "left,right", "any", "number"),
    ]
    for spec in specs:
        name, function, minimum, shape, *rest = spec
        registry.register(ToolDefinition(name, function, function.__doc__ or name, minimum, shape, *(rest or [])))
    return registry

