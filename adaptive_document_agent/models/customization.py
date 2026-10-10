"""User-authored report intent, source bindings and observable execution results."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestedSection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    section_id: str = ''
    title: str = Field(min_length=1, max_length=180)
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    start_quote: str = ''
    next_section_quote: str = ''


class ReportRequirement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=60)
    request_quote: str = Field(min_length=1, max_length=2000)
    description: str = Field(min_length=1, max_length=500)
    kind: Literal['analysis_focus', 'section_tables', 'content_detail', 'output_language',
                  'slide_limit', 'unsupported']
    resolution: Literal['resolved', 'ambiguous', 'unsupported'] = 'resolved'
    reason: str = ''
    sections: list[RequestedSection] = Field(default_factory=list)
    language: str = ''
    language_scope: Literal['body', 'source_tables', 'all'] = 'body'
    detail: Literal['concise', 'balanced', 'detailed'] = 'balanced'
    max_slides: int | None = Field(default=None, ge=1, le=500)


class ReportRequirements(BaseModel):
    model_config = ConfigDict(extra='forbid')
    original_request: str = ''
    items: list[ReportRequirement] = Field(default_factory=list, max_length=30)
    conflicts: list[str] = Field(default_factory=list)
    interpretation_error: str = ''
    # Only exact source -> display wording. Never modify analytical facts.
    copy_translations: dict[str, str] = Field(default_factory=dict)
    navigation_audit: list[dict] = Field(default_factory=list)


class RequirementCheck(BaseModel):
    requirement_id: str
    status: Literal['planned', 'satisfied', 'partial', 'not_met', 'unsupported', 'ambiguous']
    message: str
    source_pages: list[int] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    slide_numbers: list[int] = Field(default_factory=list)
    slide_ids: list[str] = Field(default_factory=list)
    verification: str = 'deterministic'
