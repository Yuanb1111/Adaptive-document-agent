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


class SemanticCandidateDecision(BaseModel):
    """Original model decision, before evidence checks or selection cutoffs."""

    candidate_id: str
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False
    reason_refs: list[str] = Field(default_factory=list)


class SemanticRationale(BaseModel):
    """A catalog entry stays a list item so duplicate IDs cannot overwrite prose."""

    id: str
    text: str


class SemanticScoringResponseAudit(BaseModel):
    """Response-wide data stored once, on the first returned candidate score."""

    reason_catalog: list[SemanticRationale] = Field(default_factory=list)
    unmatched_decisions: list[SemanticCandidateDecision] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)


class CandidateScoreAudit(BaseModel):
    """Keep every original decision, including conflicting duplicates."""

    decisions: list[SemanticCandidateDecision] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    response_audit: SemanticScoringResponseAudit | None = None


class CandidateScore(BaseModel):
    candidate: AnalysisCandidate
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False
    semantic_audit: CandidateScoreAudit | None = None


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
