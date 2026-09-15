"""Semantic resolution models."""

from pydantic import BaseModel, Field


class SemanticMapping(BaseModel):
    original_name: str
    canonical_name: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None


class DocumentEntity(BaseModel):
    name: str
    entity_type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

