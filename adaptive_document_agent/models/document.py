"""Document-level representations."""

from pydantic import BaseModel, Field

from .page import DocumentPage


class DocumentProfile(BaseModel):
    document_type: str = "Unknown document"
    document_purpose: str = "Not yet determined"
    overview_title: str = "Document overview"
    document_summary: str = ""
    document_summary_pages: list[int] = Field(default_factory=list)
    language: str | None = None
    important_sections: list[str] = Field(default_factory=list)
    detected_time_periods: list[str] = Field(default_factory=list)
    detected_units: list[str] = Field(default_factory=list)
    detected_currencies: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    important_tables: list[str] = Field(default_factory=list)
    important_figures: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    analysis_page_ranges: list[tuple[int, int]] = Field(default_factory=list)
    analysis_focus: str | None = None


class AnalysisPageRange(BaseModel):
    """A model-selected, user-reviewable page range for deeper analysis."""

    title: str
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    reason: str


class AnalysisScopePreview(BaseModel):
    """Read-only routing result shown before expensive document analysis."""

    document_id: str
    document_sha256: str
    page_count: int = Field(ge=1)
    selected_page_count: int = Field(ge=1)
    page_ranges: list[AnalysisPageRange] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    document_id: str
    sha256: str
    safe_filename: str
    page_count: int = Field(ge=0)
    pages: list[DocumentPage] = Field(default_factory=list)
    encrypted: bool = False
    warnings: list[str] = Field(default_factory=list)
