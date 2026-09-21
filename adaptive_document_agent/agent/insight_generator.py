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
        from adaptive_document_agent.services.language_qa import clean_metric_label
        from adaptive_document_agent.services.movement_formatter import analyze_trajectory

        metric_name = clean_metric_label(result.title)
        res_str = str(result.result) if result.result is not None else "reported levels"
        movement = f"{metric_name} stood at {res_str}"
        if isinstance(result.result, list) and len(result.result) >= 3:
            series_rows = [row for row in result.result if isinstance(row, dict) and row.get("value") is not None]
            if len(series_rows) >= 3:
                try:
                    values = [float(row["value"]) for row in series_rows]
                    periods = [str(row.get("period") or row.get("label") or "") for row in series_rows]
                    trajectory = analyze_trajectory(values, periods)
                    description = str(trajectory.get("description") or "").strip()
                    if description:
                        movement = f"{metric_name} {description[0].lower()}{description[1:]}"
                except (TypeError, ValueError):
                    pass
        driver = f"Management did not disclose specific operational drivers in the reported period; key sensitivity is {metric_name.lower()} trajectory."
        implication = "Requires ongoing tracking against baseline performance and liquidity requirements."
        watch_item = f"Subsequent period reporting on {metric_name.lower()}."
        narrative = f"{movement}. {driver} {implication} Watch item: {watch_item}"

        return Insight(
            id=stable_id("insight", result.task_id),
            title=result.title,
            narrative=narrative,
            kind="calculated_result",
            importance=min(1.0, result.confidence),
            confidence=result.confidence,
            evidence=result.evidence,
            result_ids=[result.task_id],
            metric=metric_name,
            movement=movement,
            driver=driver,
            implication=implication,
            watch_item=watch_item,
        )
