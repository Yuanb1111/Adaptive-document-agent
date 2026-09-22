"""Evidence-grounded insight generation after validation."""

from pydantic import BaseModel, Field

from adaptive_document_agent.models import AnalysisResult, Insight, Observation
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.utils.ids import stable_id

from .prompting import load_prompt, untrusted_document_message


class InsightList(BaseModel):
    insights: list[Insight] = Field(default_factory=list)


class InsightGenerator:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    def generate(self, results: list[AnalysisResult], observations: list[Observation] | None = None) -> list[Insight]:
        valid = [result for result in results if result.result is not None and result.evidence]
        if not self.gateway:
            return [self._deterministic(result) for result in valid]
        # Retain bounded source text so a claimed driver can actually be grounded.
        import json
        by_id = {o.id: o for o in observations or []}
        payload = json.dumps([{**r.model_dump(mode="json", exclude={"evidence"}),
            # Explicit units and periods prevent prose from describing unlabelled
            # tool dictionaries or mixing base currency with source thousands.
            "input_observations": [by_id[oid].model_dump(mode="json", include={
                "id", "metric_original", "metric_canonical", "value", "raw_value", "unit",
                "unit_family", "raw_unit", "unit_scale", "currency", "period", "period_type",
                "entity", "dimensions", "category_dimensions"})
                for oid in r.input_observation_ids if oid in by_id],
            "evidence": [{**e.model_dump(mode="json"), "text": (e.text or "")[:1200]} for e in r.evidence[:4]]}
            for r in valid], ensure_ascii=False)
        generated = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("insight_generation.txt")},
                untrusted_document_message(payload),
            ],
            InsightList,
            stage="insight",
        ).insights
        evidence_by_task = {result.task_id: result.evidence for result in valid}
        accepted = []
        by_task = {r.task_id: r for r in valid}
        for insight in generated:
            if not insight.result_ids or any(rid not in evidence_by_task for rid in insight.result_ids):
                continue
            insight.evidence = [source for identifier in insight.result_ids for source in evidence_by_task[identifier]]
            if insight.driver:
                quote = " ".join((insight.driver_quote or "").split())
                if not quote or not any(e.page == insight.driver_source_page and quote in " ".join((e.text or "").split()) for e in insight.evidence):
                    # Do not leave an unsupported driver embedded in its narrative.
                    accepted.extend(self._deterministic(by_task[rid]) for rid in insight.result_ids)
                    continue
            accepted.append(insight)
        return list({i.id: i for i in accepted if i.evidence}.values()) or [self._deterministic(r) for r in valid]

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
        narrative = f"{movement}."

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
        )
