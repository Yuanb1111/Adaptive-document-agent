"""Generate data-supported possibilities without executing them."""

from collections import defaultdict
from itertools import combinations

from pydantic import BaseModel, Field

from adaptive_document_agent.document_model import DocumentIndex, best_period_series, paired_observations
from adaptive_document_agent.models import AnalysisCandidate, DocumentProfile, Observation
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.utils.ids import stable_id

from .prompting import load_prompt, untrusted_document_message


class CandidateSelection(BaseModel):
    selected_candidate_ids: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class AnalysisCandidateGenerator:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    def generate(self, index: DocumentIndex, profile: DocumentProfile | None = None) -> list[AnalysisCandidate]:
        candidates: list[AnalysisCandidate] = []
        for metric in index.metrics():
            if metric.casefold() in {"page", "pages"}:
                continue
            observations = [item for item in index.for_metric(metric) if item.value is not None]
            period_series = best_period_series(observations)
            if period_series:
                candidates.extend(self._period_candidates(metric, period_series))
            dimension_keys = sorted({key for item in observations for key in item.dimensions})
            for key in dimension_keys:
                if key in {"period_basis", "table_context"}:
                    continue
                if len({item.dimensions.get(key) for item in observations if item.dimensions.get(key)}) >= 2:
                    candidates.extend(self._category_candidates(metric, key, observations))
        candidates.extend(self._correlation_candidates(index))
        if not self.gateway or not candidates:
            return candidates
        bounded = self._prefilter(candidates, index, profile or DocumentProfile())
        payload = {
            "document_profile": (profile or DocumentProfile()).model_dump(mode="json"),
            "data_supported_candidates": [candidate.model_dump(mode="json") for candidate in bounded],
            "instruction": "Select candidate IDs that are analytically useful. You may not add IDs or change required observations.",
        }
        selection = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("analysis_candidates.txt")},
                untrusted_document_message(str(payload)),
            ],
            CandidateSelection,
            stage="planner",
        )
        selected = set(selection.selected_candidate_ids)
        chosen = [candidate for candidate in bounded if candidate.id in selected]
        # A provider may return an empty or invalid ID list even when deterministic
        # evidence supports analyses. Keep the bounded evidence-backed set so the
        # downstream scorer can still reject or select candidates safely.
        return chosen or bounded

    @staticmethod
    def _prefilter(
        candidates: list[AnalysisCandidate],
        index: DocumentIndex,
        profile: DocumentProfile,
        *,
        maximum: int = 160,
    ) -> list[AnalysisCandidate]:
        purpose = " ".join([profile.document_purpose, *profile.metrics]).casefold()

        def priority(candidate: AnalysisCandidate) -> tuple[float, float, int, int, str]:
            observations = [index.get(identifier) for identifier in candidate.observation_ids]
            valid = [item for item in observations if item and item.value is not None]
            confidence = sum(item.confidence for item in valid) / len(valid) if valid else 0.0
            metric_names = (candidate.metric or "").casefold().split("|")
            relevance = 1.0 if any(name and name in purpose for name in metric_names) else 0.0
            periods = len({item.period for item in valid if item.period})
            support = min(len(valid), 30)
            return relevance, confidence, periods, support, candidate.id

        return sorted(candidates, key=priority, reverse=True)[:maximum]

    def _period_candidates(self, metric: str, observations: list[Observation]) -> list[AnalysisCandidate]:
        ids = [item.id for item in observations]
        types = [("absolute_change", "Change"), ("percentage_change", "Growth"), ("linear_trend", "Trend")]
        ordered = sorted(observations, key=lambda item: item.period or "")
        if len(ordered) >= 3 and float(ordered[0].value or 0) > 0 and float(ordered[-1].value or 0) >= 0:
            types.append(("cagr", "CAGR"))
        return [
            AnalysisCandidate(
                id=stable_id("candidate", analysis_type, metric),
                title=f"{metric.title()} {label}",
                analysis_type=analysis_type,
                metric=metric,
                observation_ids=ids,
                reason=f"{metric} has observations for multiple periods.",
            )
            for analysis_type, label in types
        ]

    def _category_candidates(self, metric: str, dimension: str, observations: list[Observation]) -> list[AnalysisCandidate]:
        candidates: list[AnalysisCandidate] = []
        # Group by period so category comparisons and rankings are strictly within the same period
        by_period: dict[str, list[Observation]] = defaultdict(list)
        for item in observations:
            if item.dimensions.get(dimension) and item.period:
                by_period[item.period].append(item)

        for period, p_obs in by_period.items():
            if len({it.dimensions.get(dimension) for it in p_obs}) >= 2:
                ids = [it.id for it in p_obs]
                for analysis_type in ("rank_values", "contribution_share", "compare_categories"):
                    candidates.append(
                        AnalysisCandidate(
                            id=stable_id("candidate", analysis_type, metric, dimension, period),
                            title=f"{metric.title()} by {dimension.title()} ({period})",
                            analysis_type=analysis_type,
                            metric=metric,
                            dimensions=[dimension],
                            observation_ids=ids,
                            reason=f"{metric} has multiple {dimension} categories in {period}.",
                        )
                    )
        return candidates

    def _correlation_candidates(self, index: DocumentIndex) -> list[AnalysisCandidate]:
        output: list[AnalysisCandidate] = []
        for left_name, right_name in combinations(index.metrics(), 2):
            left, right = index.for_metric(left_name), index.for_metric(right_name)
            if len(paired_observations([*left, *right], left_name, right_name)) >= 5:
                output.append(
                    AnalysisCandidate(
                        id=stable_id("candidate", "pearson_correlation", left_name, right_name),
                        title=f"{left_name.title()} and {right_name.title()} Relationship",
                        analysis_type="pearson_correlation",
                        metric=f"{left_name}|{right_name}",
                        observation_ids=[item.id for item in [*left, *right]],
                        reason="At least five paired observations exist.",
                    )
                )
        return output
