"""Create executable analysis tasks only from accepted candidates."""

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import AnalysisTask, CandidateScore


class AnalysisPlanner:
    def plan(self, scores: list[CandidateScore], index: DocumentIndex) -> list[AnalysisTask]:
        tasks: list[AnalysisTask] = []
        seen: set[tuple[str, str | None]] = set()
        for score in scores:
            candidate = score.candidate
            key = candidate.analysis_type, candidate.metric
            if score.rejected or key in seen:
                continue
            available = [index.get(identifier) for identifier in candidate.observation_ids]
            if not any(item and item.value is not None for item in available):
                continue
            seen.add(key)
            tasks.append(
                AnalysisTask(
                    id=candidate.id.replace("candidate_", "task_", 1),
                    title=candidate.title,
                    description=candidate.reason,
                    analysis_type=candidate.analysis_type,
                    tool_name=candidate.analysis_type,
                    required_metrics=(candidate.metric or "").split("|") if candidate.metric else [],
                    required_dimensions=candidate.dimensions,
                    observation_query={"observation_ids": candidate.observation_ids},
                    reason=candidate.reason,
                    expected_output="Validated deterministic calculation",
                    priority=int(round(score.score * 100)),
                    confidence_requirement=0.35,
                )
            )
        return sorted(tasks, key=lambda task: task.priority, reverse=True)

