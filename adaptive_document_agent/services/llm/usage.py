"""Provider usage metadata."""

from pydantic import BaseModel, Field


class LLMUsage(BaseModel):
    provider: str
    model: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    resolved_model: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    cached_input_tokens: int | None = Field(default=None, ge=0)
    uncached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    thinking_mode: str | None = None
    request_chars: int | None = Field(default=None, ge=0)
    response_chars: int | None = Field(default=None, ge=0)
    cost_currency: str | None = None
    cost_details: dict = Field(default_factory=dict)

