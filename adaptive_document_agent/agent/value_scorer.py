"""Bound candidate volume using relevance, evidence, and redundancy signals."""

from collections import Counter, defaultdict

from pydantic import BaseModel, Field

from adaptive_document_agent.document_model import DocumentIndex, paired_observations
from adaptive_document_agent.models import AnalysisCandidate, CandidateScore, DocumentProfile, Observation
from adaptive_document_agent.models.analysis import (
    CandidateScoreAudit,
    SemanticCandidateDecision,
    SemanticRationale,
    SemanticScoringResponseAudit,
)
from adaptive_document_agent.services.llm import LLMGateway

from .prompting import load_prompt, untrusted_document_message
from .candidate_generator import AnalysisCandidateGenerator


# Use the same type on the wire and in saved audit records so cache/export
# round trips retain model identity as well as all original values.
SemanticCandidateScore = SemanticCandidateDecision


class SemanticCandidateScores(BaseModel):
    reason_catalog: list[SemanticRationale] = Field(default_factory=list)
    scores: list[SemanticCandidateScore] = Field(default_factory=list)


def _scoring_payload(candidates: list[AnalysisCandidate], profile: DocumentProfile) -> dict:
    """Intern only identical source rationale; keep every other candidate field."""
    original = {
        "document_profile": profile.model_dump(mode="json"),
        "candidates": [item.model_dump(mode="json") for item in candidates],
    }
    counts = Counter(item.reason for item in candidates)
    reason_ids = {reason: f"s{position}" for position, reason in enumerate(
        (reason for reason, count in counts.items() if count > 1), start=1,
    )}
    if not reason_ids:
        return original
    compact_candidates = []
    for candidate in original["candidates"]:
        item = dict(candidate)
        if item["reason"] in reason_ids:
            item["source_reason_ref"] = reason_ids[item.pop("reason")]
        compact_candidates.append(item)
    compact = {
        "document_profile": original["document_profile"],
        "source_reason_catalog": {reference: reason for reason, reference in reason_ids.items()},
        "candidates": compact_candidates,
    }
    # Small/short repetitions can cost more reference overhead than they save.
    return compact if len(str(compact)) < len(str(original)) else original


def _expand_reasons(decision: SemanticCandidateDecision, catalog: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Resolve exact prose and quarantine incomplete explanations without erasing them."""
    reasons: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for reference in decision.reason_refs:
        if reference in seen:
            errors.append(f"duplicate rationale reference: {reference!r}")
        seen.add(reference)
        if not reference.strip():
            errors.append("blank rationale reference")
        elif reference not in catalog:
            errors.append(f"unknown rationale reference: {reference!r}")
        else:
            if len(catalog[reference]) > 1:
                errors.append(f"duplicate rationale catalog ID: {reference!r}")
            for reason in catalog[reference]:
                if reason.strip():
                    reasons.append(reason)
                else:
                    errors.append(f"blank rationale catalog entry: {reference!r}")
    for reason in decision.reasons:
        if reason.strip():
            reasons.append(reason)
        else:
            errors.append("blank inline rationale")
    if not reasons:
        errors.append("model candidate decision has no intelligible rationale")
    return reasons, errors


def _response_audit(response: SemanticCandidateScores, valid_ids: set[str]) -> SemanticScoringResponseAudit:
    unmatched = [item for item in response.scores if item.candidate_id not in valid_ids]
    errors = [f"unknown candidate ID: {item.candidate_id!r}" for item in unmatched]
    counts = Counter(entry.id for entry in response.reason_catalog)
    for entry in response.reason_catalog:
        if not entry.id.strip() or not entry.text.strip():
            errors.append(f"blank rationale catalog ID or text: {entry.id!r}")
    errors.extend(f"duplicate rationale catalog ID: {reference!r}" for reference, count in counts.items() if count > 1)
    return SemanticScoringResponseAudit(
        reason_catalog=response.reason_catalog, unmatched_decisions=unmatched, validation_errors=errors,
    )


class AnalysisValueScorer:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    def score(self, candidates: list[AnalysisCandidate], index: DocumentIndex, profile: DocumentProfile, *, maximum: int = 20) -> list[CandidateScore]:
        bounded = AnalysisCandidateGenerator._prefilter(candidates, index, profile) if self.gateway else candidates
        response = self._semantic_scores(bounded, profile)
        bounded_ids = {item.id for item in bounded}
        decisions: dict[str, list[SemanticCandidateDecision]] = defaultdict(list)
        catalog: dict[str, list[str]] = defaultdict(list)
        if response is not None:
            for entry in response.reason_catalog:
                catalog[entry.id].append(entry.text)
            for decision in response.scores:
                if decision.candidate_id in bounded_ids:
                    decisions[decision.candidate_id].append(decision)
        input_id_counts = Counter(item.id for item in candidates)
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
            audit = CandidateScoreAudit(decisions=decisions[candidate.id]) if response is not None else None
            semantic_reasons: list[str] = []
            if audit is not None:
                for decision in audit.decisions:
                    expanded, errors = _expand_reasons(decision, catalog)
                    semantic_reasons.extend(expanded)
                    audit.validation_errors.extend(errors)
                if len(audit.decisions) > 1:
                    audit.validation_errors.append("model returned multiple candidate decisions")
                if input_id_counts[candidate.id] > 1:
                    audit.validation_errors.append("duplicate supplied candidate ID")
                if not audit.decisions:
                    audit.validation_errors.append("outside candidate review budget" if candidate.id not in bounded_ids else "model omitted candidate decision")
            semantic = audit.decisions[0] if audit and len(audit.decisions) == 1 and not audit.validation_errors else None
            score = 0.3 * evidence_score + 0.7 * semantic.score if semantic else evidence_score
            rejected = support < self._minimum(candidate.analysis_type) or confidence < 0.35 or bool(semantic and semantic.rejected)
            reasons = [f"mean input confidence={confidence:.2f}", f"comparable support={support}"]
            reasons.extend(semantic_reasons)
            if self.gateway and semantic is None:
                rejected = True
                reasons.extend(audit.validation_errors if audit else ["model omitted candidate decision"])
            if support < self._minimum(candidate.analysis_type) or confidence < 0.35:
                reasons.append("insufficient or low-confidence evidence")
            scored.append(CandidateScore(candidate=candidate, score=max(0.0, min(1.0, score)), reasons=reasons, rejected=rejected, semantic_audit=audit))
        accepted = sorted((item for item in scored if not item.rejected), key=lambda item: item.score, reverse=True)[:maximum]
        accepted_ids = {item.candidate.id for item in accepted}
        for item in scored:
            if not item.rejected and item.candidate.id not in accepted_ids:
                item.rejected = True
                item.reasons.append("below bounded top-candidate cutoff")
        ranked = sorted(scored, key=lambda item: item.score, reverse=True)
        if ranked and response is not None:
            # Keep the complete response-level audit once, even if all candidates
            # were rejected. Each candidate separately retains every raw decision.
            ranked[0].semantic_audit.response_audit = _response_audit(response, bounded_ids)
        return ranked

    def _semantic_scores(self, candidates: list[AnalysisCandidate], profile: DocumentProfile) -> SemanticCandidateScores | None:
        if not self.gateway or not candidates:
            return None
        response = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("analysis_planner.txt") + "\nSelect and score candidates in ONE response. Return exactly one decision per supplied candidate ID: score, rejected (true means not selected), and explicit reasons. Assess analytical usefulness, redundancy and evidence. Never add candidate IDs. "
                 "Write repeated rationale once in reason_catalog as entries with unique short id and full text; reference those IDs in each applicable decision's ordered reason_refs. Put complete candidate-specific reasons, exceptions, evidence qualifications and caveats in reasons. A decision's explanation is its referenced catalog text in order followed by its inline reasons. Use only references defined in reason_catalog. Every accepted AND rejected decision needs a complete, nonblank explanation. Do not drop candidates, evidence, qualifications or unique reasoning to compress the response. "
                 "Input source_reason_ref resolves the candidate's original reason verbatim in source_reason_catalog; it is source data, not a scoring decision or an output rationale reference."},
                untrusted_document_message(str(_scoring_payload(candidates, profile))),
            ],
            SemanticCandidateScores,
            stage="planner",
        )
        return response

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
