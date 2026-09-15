"""Page and image representations."""

from pydantic import BaseModel, Field

from .table import ExtractedTable


class PageImage(BaseModel):
    image_id: str
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    requires_vision: bool = True
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class DocumentPage(BaseModel):
    page_number: int = Field(ge=1)
    text: str = ""
    tables: list[ExtractedTable] = Field(default_factory=list)
    images: list[PageImage] = Field(default_factory=list)
    extraction_quality: float = Field(default=1.0, ge=0.0, le=1.0)
    requires_ocr: bool = False
    text_blocks: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
