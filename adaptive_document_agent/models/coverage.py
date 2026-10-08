"""Source processing extent, separate from semantic/business acceptance."""
from typing import Literal
from pydantic import BaseModel, Field


class SourceSection(BaseModel):
    id: str
    title: str
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    level: int = Field(default=1, ge=1)
    origin: Literal['pdf_outline', 'page_window'] = 'pdf_outline'


class SectionCoverage(SourceSection):
    selected_pages: list[int] = Field(default_factory=list)
    selection_reasons: list[str] = Field(default_factory=list)
    processing_status: Literal['unselected', 'partially_selected', 'selected'] = 'unselected'
    observation_ids: list[str] = Field(default_factory=list)
    planned_topic_ids: list[str] = Field(default_factory=list)
    # Planned themes are not proof that the renderer exported those themes.
    export_mapping_status: str = 'not_recorded'
    exported_topic_ids: list[str] = Field(default_factory=list)
    exported_slide_numbers: list[int] = Field(default_factory=list)


class SourceCheck(BaseModel):
    section_id: str
    pages: list[int] = Field(default_factory=list)
    reason: str
    decision_impact: str
    status: Literal['unchecked', 'checked_found', 'checked_not_found', 'incomplete', 'failed'] = 'unchecked'
    finding: str = ''
    evidence_quotes: dict[int, list[str]] = Field(default_factory=dict)


class SourceCoverage(BaseModel):
    version: str = 'source-coverage-v1'
    sections: list[SectionCoverage] = Field(default_factory=list)
    checks: list[SourceCheck] = Field(default_factory=list)
    calls_used: int = 0
    max_calls: int = 3
    max_supplementary_pages: int = 6
    max_output_tokens_per_call: int = 2048
    notes: list[str] = Field(default_factory=list)
    # Source checks search bounded excerpts; they never certify non-disclosure.
    full_source_review_complete: bool = False
