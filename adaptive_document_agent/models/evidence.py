"""Page-level provenance models."""

from pydantic import BaseModel, Field, field_validator


class SourceEvidence(BaseModel):
    """Traceable source for a fact, calculation input, or interpretation."""

    page: int = Field(ge=1)
    text: str | None = None
    table_id: str | None = None
    row_label: str | None = None
    column_label: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    extraction_method: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("text")
    @classmethod
    def trim_source_text(cls, value: str | None) -> str | None:
        return value.strip() if value else value

