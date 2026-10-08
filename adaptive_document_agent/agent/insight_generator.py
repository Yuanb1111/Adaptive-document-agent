"""Evidence-grounded insight generation after validation."""

import json

from pydantic import BaseModel, Field

from adaptive_document_agent.models import AnalysisResult, Insight, Observation, ParsedDocument, ValidationIssue
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.utils.ids import stable_id

from .prompting import load_prompt, untrusted_document_message
from .insight_source_context import build_source_contexts, matched_driver_evidence


class InsightList(BaseModel):
    insights: list[Insight] = Field(default_factory=list)


class InsightGenerator:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway
        self.validation_issues: list[ValidationIssue] = []

    def generate(
        self, results: list[AnalysisResult], observations: list[Observation] | None = None,
        *, document: ParsedDocument | None = None,
    ) -> list[Insight]:
        valid = [result for result in results if result.result is not None and result.evidence]
        self.validation_issues = []
        from adaptive_document_agent.validation.insight_context import qualified_metric_label, validate_insight_contexts
        if not self.gateway or not valid:
            return [self._deterministic(result, observations) for result in valid]
        contexts = build_source_contexts(valid, observations or [], document)
        by_id = {o.id: o for o in observations or []}
        payload = json.dumps([{**r.model_dump(mode="json", exclude={"evidence"}),
            # Explicit units and periods prevent prose from describing unlabelled
            # tool dictionaries or mixing base currency with source thousands.
            "input_observations": [{**by_id[oid].model_dump(mode="json", include={
                "id", "metric_original", "metric_canonical", "value", "raw_value", "unit",
                "unit_family", "raw_unit", "unit_scale", "currency", "period", "period_type",
                "entity", "dimensions", "category_dimensions", "parent_section", "source_table", "table_id"}),
                "qualified_metric_label": qualified_metric_label(by_id[oid])}
                for oid in r.input_observation_ids if oid in by_id],
            "evidence": [{**e.model_dump(mode="json"), "text": (e.text or "")[:1200]} for e in r.evidence[:4]],
            "source_context": {
                "coverage": "Bounded source excerpts; not a complete review of the document.",
                "selection": "Source pages, adjacent pages, and lexical matches; relevance is not established.",
                "driver_citation_source": "excerpts" if document is not None else "evidence",
                "excerpts": [excerpt.payload() for excerpt in contexts[r.task_id]],
            }}
            for r in valid], ensure_ascii=False)
        generated = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("insight_generation.txt")},
                untrusted_document_message(payload),
            ],
            InsightList,
            stage="insight",
        ).insights
        generated, self.validation_issues = validate_insight_contexts(generated, valid, observations or [])
        evidence_by_task = {result.task_id: result.evidence for result in valid}
        accepted = []
        by_task = {r.task_id: r for r in valid}
        for insight in generated:
            if not insight.result_ids or any(rid not in evidence_by_task for rid in insight.result_ids):
                continue
            insight.evidence = [source for identifier in insight.result_ids for source in evidence_by_task[identifier]]
            if insight.driver or insight.driver_quote or insight.driver_source_page is not None:
                # Validate against exactly the windows supplied for this result.
                # A quote elsewhere in the PDF or another task is not sufficient.
                excerpts = [excerpt for rid in insight.result_ids for excerpt in contexts[rid]]
                legacy = [source.model_copy(update={"text": (source.text or "")[:1200]})
                          for rid in insight.result_ids for source in evidence_by_task[rid][:4]]
                driver_source = matched_driver_evidence(
                    insight.driver_quote, insight.driver_source_page, excerpts,
                    legacy_evidence=legacy if document is None else None,
                ) if insight.driver else None
                if driver_source is None:
                    # Do not leave an unsupported driver embedded in its narrative.
                    self.validation_issues.append(ValidationIssue(
                        code="insight_driver_evidence", stage="insight", severity="warning",
                        message="A reported explanation could not be matched to its supplied source page; "
                                "the draft was replaced with the validated calculation.",
                        related_ids=[insight.id, *insight.result_ids], evidence=insight.evidence,
                    ))
                    accepted.extend(self._deterministic(by_task[rid], observations) for rid in insight.result_ids)
                    continue
                if driver_source not in insight.evidence:
                    insight.evidence.append(driver_source)
                insight.driver_quote = driver_source.text
                insight.confidence = min(insight.confidence, driver_source.confidence,
                                         *(by_task[rid].confidence for rid in insight.result_ids))
            accepted.append(insight)
        return list({i.id: i for i in accepted if i.evidence}.values()) or [self._deterministic(r, observations) for r in valid]

    @staticmethod
    def _deterministic(result: AnalysisResult, observations: list[Observation] | None = None) -> Insight:
        from adaptive_document_agent.services.language_qa import clean_metric_label
        from adaptive_document_agent.services.movement_formatter import analyze_trajectory

        from adaptive_document_agent.validation.insight_context import qualified_metric_label
        labels = list(dict.fromkeys(qualified_metric_label(item) for item in observations or []
                                  if item.id in result.input_observation_ids))
        metric_name = "; ".join(labels) if labels else clean_metric_label(result.title)
        res_str = str(result.result) if result.result is not None else "reported levels"
        movement = f"Calculated result for {result.title}: {res_str}"
        kind = "calculated_result"
        # A scalar tool result does not carry its operation or output unit.
        # It may be growth, a ratio or a statistic, never necessarily a level
        # of the input metric. Preserve the reported inputs instead of guessing.
        linked = [item for item in observations or []
                  if item.id in result.input_observation_ids and item.evidence]
        if isinstance(result.result, (int, float)) and linked:
            parts = []
            for item in linked[:6]:
                context = "; ".join(value for value in (item.period, item.raw_unit) if value)
                parts.append(f"{qualified_metric_label(item)}: {item.raw_value}"
                             + (f" ({context})" if context else ""))
            movement = "Selected reported values — " + "; ".join(parts)
            kind = "reported_fact"
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
            title=metric_name if labels else result.title,
            narrative=narrative,
            kind=kind,
            importance=min(1.0, result.confidence),
            confidence=result.confidence,
            evidence=result.evidence,
            result_ids=[result.task_id],
            metric=metric_name,
            movement=movement,
        )
