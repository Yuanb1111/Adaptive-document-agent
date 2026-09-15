"""Analysis planning and result models."""

from typing import Any

from pydantic import BaseModel, Field

from .evidence import SourceEvidence


class AnalysisCandidate(BaseModel):
    id: str
    title: str
    analysis_type: str
    metric: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    reason: str


class CandidateScore(BaseModel):
    candidate: AnalysisCandidate
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False


class AnalysisTask(BaseModel):
    id: str
    title: str
    description: str
    analysis_type: str
    tool_name: str | None = None
    required_metrics: list[str] = Field(default_factory=list)
    required_dimensions: list[str] = Field(default_factory=list)
    observation_query: dict[str, Any] = Field(default_factory=dict)
    formula: str | None = None
    reason: str
    expected_output: str
    priority: int = Field(default=50, ge=0, le=100)
    confidence_requirement: float | None = Field(default=None, ge=0.0, le=1.0)


class AnalysisResult(BaseModel):
    task_id: str
    title: str
    result_type: str = "calculated"
    result: Any = None
    input_observation_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

