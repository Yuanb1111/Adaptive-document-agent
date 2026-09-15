"""Evidence-grounded insight generation after validation."""

from pydantic import BaseModel, Field

from adaptive_document_agent.models import AnalysisResult, Insight
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.utils.ids import stable_id

from .prompting import load_prompt, untrusted_document_message


class InsightList(BaseModel):
    insights: list[Insight] = Field(default_factory=list)


class InsightGenerator:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    def generate(self, results: list[AnalysisResult]) -> list[Insight]:
        valid = [result for result in results if result.result is not None and result.evidence]
        if not self.gateway:
            return [self._deterministic(result) for result in valid]
        payload = "\n".join(result.model_dump_json(exclude={"evidence": {"__all__": {"text"}}}) for result in valid)
        generated = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("insight_generation.txt")},
                untrusted_document_message(payload),
            ],
            InsightList,
            stage="insight",
        ).insights
        evidence_by_task = {result.task_id: result.evidence for result in valid}
        for insight in generated:
            if not insight.evidence:
                insight.evidence = [source for identifier in insight.result_ids for source in evidence_by_task.get(identifier, [])]
        return [insight for insight in generated if insight.evidence]

    @staticmethod
    def _deterministic(result: AnalysisResult) -> Insight:
        return Insight(
            id=stable_id("insight", result.task_id),
            title=result.title,
            narrative=f"The deterministic analysis produced: {result.result}.",
            kind="calculated_result",
            importance=min(1.0, result.confidence),
            confidence=result.confidence,
            evidence=result.evidence,
            result_ids=[result.task_id],
        )

