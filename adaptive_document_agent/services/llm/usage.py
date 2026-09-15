"""Provider usage metadata."""

from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    provider: str
    model: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)

