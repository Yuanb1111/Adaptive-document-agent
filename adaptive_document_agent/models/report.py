"""Insight, report, and complete pipeline result models."""

from typing import Literal

from pydantic import BaseModel, Field

from .analysis import AnalysisCandidate, AnalysisResult, AnalysisTask, CandidateScore
from .chart import ChartPlan
from .document import DocumentProfile, ParsedDocument
from .evidence import SourceEvidence
from .observation import Observation
from .presentation import PresentationPlan
from .validation import ValidationIssue


class Insight(BaseModel):
    id: str
    title: str
    narrative: str
    kind: Literal["reported_fact", "calculated_result", "interpretation"]
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    result_ids: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    title: str
    purpose: str
    insight_ids: list[str] = Field(default_factory=list)


class ReportPlan(BaseModel):
    title: str = "Adaptive Document Analysis"
    sections: list[ReportSection] = Field(default_factory=list)


class PipelineResult(BaseModel):
    document: ParsedDocument
    profile: DocumentProfile
    observations: list[Observation] = Field(default_factory=list)
    candidates: list[AnalysisCandidate] = Field(default_factory=list)
    candidate_scores: list[CandidateScore] = Field(default_factory=list)
    analysis_plan: list[AnalysisTask] = Field(default_factory=list)
    analysis_results: list[AnalysisResult] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    report_plan: ReportPlan = Field(default_factory=ReportPlan)
    presentation_plan: PresentationPlan | None = None
    report_markdown: str = ""
    charts: list[ChartPlan] = Field(default_factory=list)
    validation_warnings: list[ValidationIssue] = Field(default_factory=list)
    llm_usage: list[dict[str, object]] = Field(default_factory=list)
    timings_ms: dict[str, int] = Field(default_factory=dict)
