"""Optional vision contract with explicit capability checks."""

from pydantic import BaseModel, Field

from adaptive_document_agent.services.llm import LLMGateway


class ChartInterpretation(BaseModel):
    title: str | None = None
    chart_type: str | None = None
    axis_labels: list[str] = Field(default_factory=list)
    legend: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    periods: list[str] = Field(default_factory=list)
    approximate_values: list[dict[str, object]] = Field(default_factory=list)
    main_trend: str | None = None
    annotations: list[str] = Field(default_factory=list)
    confidence: float = 0.4


class VisionAdapter:
    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    @property
    def enabled(self) -> bool:
        return self.gateway.client.supports("vision")

    def unavailable_message(self) -> str | None:
        return None if self.enabled else "Chart candidates were detected, but the configured model does not declare vision support."

