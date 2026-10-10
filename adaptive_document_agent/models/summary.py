"""Complete source-bound introductory reading and model-authored slide decisions."""
from typing import Literal
from pydantic import BaseModel, Field


class SummaryPageRange(BaseModel):
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=400)


class SummarySourceBlock(BaseModel):
    id: str
    page: int
    char_start: int
    char_end: int
    text: str


class SummaryFact(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=6000)
    source_quote: str = Field(min_length=8, max_length=6000)
    source_pages: list[int] = Field(min_length=1)


class SummaryPart(BaseModel):
    id: str
    title: str
    role: Literal['content', 'heading', 'layout']
    block_id: str
    start_line: int
    end_line: int
    source_page: int
    source_text: str
    reading_note: str
    facts: list[SummaryFact] = Field(default_factory=list)


class SummarySlideItem(SummaryFact):
    text: str = Field(min_length=1, max_length=180)
    part_ids: list[str] = Field(min_length=1)
    continuation_group: str = ''
    continuation_index: int = Field(default=0, ge=0)
    continuation_count: int = Field(default=1, ge=1)
    continuation_digest: str = ''
    reading_fact_copy: bool = False


class SummarySlidePage(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=65)
    source_section: str = Field(min_length=1, max_length=160)
    items: list[SummarySlideItem] = Field(min_length=1, max_length=4)


class SummaryPartDecision(BaseModel):
    part_id: str
    decision: Literal['include', 'omit']
    reason: str = Field(min_length=1, max_length=400)


class SummaryReview(BaseModel):
    version: str = 'summary-reading-v2-complete-content'
    document_id: str
    document_sha256: str
    source_pages: list[int]
    scope_ranges: list[SummaryPageRange] = Field(default_factory=list)
    status: Literal['incomplete', 'complete'] = 'incomplete'
    source_blocks: list[SummarySourceBlock] = Field(default_factory=list)
    parts: list[SummaryPart] = Field(default_factory=list)
    decisions: list[SummaryPartDecision] = Field(default_factory=list)
    read_audits: list[dict] = Field(default_factory=list)
    plan_audits: list[dict] = Field(default_factory=list)
    timings_ms: dict[str, int] = Field(default_factory=dict)
