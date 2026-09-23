"""Bound candidate volume using relevance, evidence, and redundancy signals."""

from pydantic import BaseModel, Field

from adaptive_document_agent.document_model import DocumentIndex, paired_observations
from adaptive_document_agent.models import AnalysisCandidate, CandidateScore, DocumentProfile, Observation
from adaptive_document_agent.services.llm import LLMGateway

from .prompting import load_prompt, untrusted_document_message
from .candidate_generator import AnalysisCandidateGenerator


class SemanticCandidateScore(BaseModel):
    candidate_id: str
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False


class SemanticCandidateScores(BaseModel):
    scores: list[SemanticCandidateScore] = Field(default_factory=list)


class AnalysisValueScorer:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    def score(self, candidates: list[AnalysisCandidate], index: DocumentIndex, profile: DocumentProfile, *, maximum: int = 20) -> list[CandidateScore]:
        bounded = AnalysisCandidateGenerator._prefilter(candidates, index, profile) if self.gateway else candidates
        semantic_scores = self._semantic_scores(bounded, profile)
        bounded_ids = {item.id for item in bounded}
        scored: list[CandidateScore] = []
        purpose_terms = (profile.document_purpose + " " + " ".join(profile.metrics)).casefold()
        for candidate in candidates:
            observations = [index.get(identifier) for identifier in candidate.observation_ids]
            valid = [item for item in observations if item and item.value is not None]
            confidence = sum(item.confidence for item in valid) / len(valid) if valid else 0.0
            support = self._support_count(candidate, valid)
            completeness = min(1.0, support / max(self._minimum(candidate.analysis_type), 1))
            relevance = 1.0 if candidate.metric and any(term in purpose_terms for term in candidate.metric.casefold().split("|")) else 0.5
            evidence_score = 0.5 * confidence + 0.3 * completeness + 0.2 * relevance
            semantic = semantic_scores.get(candidate.id)
            score = 0.3 * evidence_score + 0.7 * semantic.score if semantic else evidence_score
            rejected = support < self._minimum(candidate.analysis_type) or confidence < 0.35 or bool(semantic and semantic.rejected)
            reasons = [f"mean input confidence={confidence:.2f}", f"comparable support={support}"]
            if semantic:
                reasons.extend(semantic.reasons)
            if self.gateway and semantic is None:
                rejected = True
                reasons.append("outside candidate review budget" if candidate.id not in bounded_ids else "model omitted candidate decision")
            if support < self._minimum(candidate.analysis_type) or confidence < 0.35:
                reasons.append("insufficient or low-confidence evidence")
            scored.append(CandidateScore(candidate=candidate, score=max(0.0, min(1.0, score)), reasons=reasons, rejected=rejected))
        accepted = sorted((item for item in scored if not item.rejected), key=lambda item: item.score, reverse=True)[:maximum]
        accepted_ids = {item.candidate.id for item in accepted}
        for item in scored:
            if not item.rejected and item.candidate.id not in accepted_ids:
                item.rejected = True
                item.reasons.append("below bounded top-candidate cutoff")
        return sorted(scored, key=lambda item: item.score, reverse=True)

    def _semantic_scores(self, candidates: list[AnalysisCandidate], profile: DocumentProfile) -> dict[str, SemanticCandidateScore]:
        if not self.gateway or not candidates:
            return {}
        response = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("analysis_planner.txt") + "\nSelect and score candidates in ONE response. Return exactly one decision per supplied candidate ID: score, rejected (true means not selected), and explicit reasons. Assess analytical usefulness, redundancy and evidence. Never add candidate IDs."},
                untrusted_document_message(str({"document_profile": profile.model_dump(mode="json"), "candidates": [item.model_dump(mode="json") for item in candidates]})),
            ],
            SemanticCandidateScores,
            stage="planner",
        )
        valid_ids = {candidate.id for candidate in candidates}
        return {item.candidate_id: item for item in response.scores if item.candidate_id in valid_ids}

    @staticmethod
    def _minimum(analysis_type: str) -> int:
        return {"pearson_correlation": 5, "spearman_correlation": 5, "linear_trend": 3, "iqr_outliers": 5, "zscore_outliers": 5}.get(analysis_type, 2)

    @staticmethod
    def _support_count(candidate: AnalysisCandidate, observations: list[Observation]) -> int:
        if candidate.analysis_type not in {"pearson_correlation", "spearman_correlation"}:
            return len(observations)
        metrics = (candidate.metric or "").split("|")
        if len(metrics) != 2:
            return 0
        return len(paired_observations(observations, metrics[0], metrics[1]))
