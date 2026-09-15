"""Model capability declaration."""

from pydantic import BaseModel


class ModelCapabilities(BaseModel):
    structured_output: bool = False
    json_mode: bool = False
    tool_calling: bool = False
    vision: bool = False
    reasoning: bool = False
    max_context_tokens: int | None = None

