"""Chart plan with data provenance."""

from typing import Literal

from pydantic import BaseModel, Field


ChartType = Literal["line", "bar", "horizontal_bar", "area", "pie", "scatter", "table"]


class ChartPlan(BaseModel):
    id: str
    title: str
    chart_type: ChartType
    available_chart_types: list[ChartType] = Field(default_factory=list)
    question: str
    observation_ids: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    analysis_task_id: str | None = None
    x_metric: str | None = None
    y_metric: str | None = None
    x_dimension: str | None = None
    x_axis_title: str = "Category or period"
    y_axis_title: str = "Value"
    show_data_labels: bool = True
