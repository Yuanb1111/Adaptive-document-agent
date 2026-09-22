"""Evidence-bound presentation narrative models."""

from typing import Literal

from pydantic import BaseModel, Field

from .chart import ChartType


PresentationSlideType = Literal[
    "cover",
    "company_overview",
    "executive_summary",
    "analysis",
    "risks",
    "data_quality",
    "appendix",
]

PresentationLayout = Literal[
    "auto",
    "single",
    "two_up",
    "three_up",
    "hero_plus_supporting",
    "chart_with_data",
    "data_overview",
    "chart_plus_kpis",
    "chart_plus_commentary",
    "two_chart_comparison",
    "combo_chart",
    "table_plus_kpis",
    "single_metric_hero",
    "kpi_band",
]

PresentationSlideRole = Literal["overview", "deep_dive", "drivers", "watch_items", "risk", "methodology", "source_data"]

PresentationBlockRole = Literal["hero", "supporting", "kpi", "table", "commentary"]


class CompanyFact(BaseModel):
    """One source-supported fact shown on the company overview slide."""

    label: str
    value: str
    source_pages: list[int] = Field(default_factory=list)


class CompanyProfile(BaseModel):
    """Source-only company or document identity selected by the planner."""

    name: str = ""
    one_line_description: str = ""
    industry: str = ""
    headquarters: str = ""
    listing_market: str = ""
    stock_code: str = ""
    offering_type: str = ""
    reporting_currency: str = ""
    document_type: str = ""
    track_record_period: str = ""
    products: list[str] = Field(default_factory=list, max_length=6)
    segments: list[str] = Field(default_factory=list, max_length=6)
    geographies: list[str] = Field(default_factory=list, max_length=6)
    business_model: str = ""
    customer_types: list[str] = Field(default_factory=list, max_length=6)
    market_position: str = ""
    listing_facts: list[str] = Field(default_factory=list, max_length=6)
    identity_state: Literal["UNRESOLVED", "PARTIALLY_RESOLVED", "RESOLVED"] = "UNRESOLVED"
    key_facts: list[CompanyFact] = Field(default_factory=list, max_length=8)
    source_pages: list[int] = Field(default_factory=list)
    field_source_pages: dict[str, list[int]] = Field(default_factory=dict)


class PresentationVisualBlock(BaseModel):
    """One evidence block placed by the deterministic slide compositor."""

    role: PresentationBlockRole
    title: str = ""
    chart_ids: list[str] = Field(default_factory=list, max_length=2)
    observation_ids: list[str] = Field(default_factory=list, max_length=12)
    insight_ids: list[str] = Field(default_factory=list, max_length=3)
    chart_type: ChartType | None = None


class PresentationSlide(BaseModel):
    """One narrative instruction whose facts must reference retained IDs."""

    id: str
    slide_type: PresentationSlideType
    title: str
    section_id: str = ""
    section_title: str = ""
    slide_role: PresentationSlideRole = "overview"
    layout: PresentationLayout = "auto"
    message: str = ""
    bullets: list[str] = Field(default_factory=list, max_length=5)
    chart_ids: list[str] = Field(default_factory=list, max_length=3)
    observation_ids: list[str] = Field(default_factory=list, max_length=40)
    insight_ids: list[str] = Field(default_factory=list, max_length=6)
    visual_blocks: list[PresentationVisualBlock] = Field(default_factory=list, max_length=4)
    source_pages: list[int] = Field(default_factory=list)
    theme_id: str = ""
    analytical_question: str = ""
    selection_reason: str = ""
    comparison_mode: Literal["context", "parallel", "like_for_like"] = "context"
    calculation_ids: list[str] = Field(default_factory=list, max_length=12)


class PresentationTheme(BaseModel):
    """Model-selected analytical question and its explicit evidence boundary."""

    id: str
    title: str
    question: str
    rationale: str
    chart_ids: list[str] = Field(default_factory=list, max_length=12)
    observation_ids: list[str] = Field(default_factory=list, max_length=180)
    insight_ids: list[str] = Field(default_factory=list, max_length=12)
    caveats: list[str] = Field(default_factory=list, max_length=5)
    source_pages: list[int] = Field(default_factory=list)


class PresentationPlan(BaseModel):
    """AI-selected story plan consumed by the deterministic PPT renderer."""

    title: str
    report_type: str = "Document analysis"
    company: CompanyProfile = Field(default_factory=CompanyProfile)
    planning_origin: Literal["model", "repaired", "fallback", "legacy"] = "legacy"
    editorial_status: Literal["unreviewed", "ready", "needs_review", "degraded"] = "unreviewed"
    editorial_notes: list[str] = Field(default_factory=list)
    # Empty remains supported for cached plans created before theme planning.
    themes: list[PresentationTheme] = Field(default_factory=list, max_length=12)
    slides: list[PresentationSlide] = Field(default_factory=list, max_length=24)
