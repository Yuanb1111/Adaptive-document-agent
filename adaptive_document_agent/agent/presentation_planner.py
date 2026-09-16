"""AI analyst that selects and organises an evidence-bound slide narrative."""

import json

from adaptive_document_agent.document_model import is_meaningful_metric
from adaptive_document_agent.models import ChartPlan, DocumentProfile, Observation, ParsedDocument, PipelineResult, PresentationPlan
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

from .prompting import load_prompt, untrusted_document_message


class PresentationPlanner:
    """Use the configured model to write a story plan without changing facts."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def plan(self, result: PipelineResult) -> PresentationPlan:
        payload = {
            "document_profile": result.profile.model_dump(mode="json"),
            "document_page_count": result.document.page_count,
            "page_excerpts": self._page_excerpts(result.document, result.profile, result.observations),
            "observations": self._observation_catalog(result.observations, result.charts),
            "insights": [
                {
                    **item.model_dump(mode="json", exclude={"evidence"}),
                    "source_pages": sorted({source.page for source in item.evidence}),
                }
                for item in result.insights
            ],
            "charts": [item.model_dump(mode="json") for item in result.charts],
            "report_title": result.report_plan.title,
        }
        proposed = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("presentation_planning.txt")},
                untrusted_document_message(json.dumps(payload, ensure_ascii=False)),
            ],
            PresentationPlan,
            stage="presentation",
        )
        return PresentationPlanValidator().validate(proposed, result)

    @staticmethod
    def _observation_catalog(observations: list[Observation], charts: list[ChartPlan]) -> list[dict[str, object]]:
        chart_observation_ids = {identifier for chart in charts for identifier in chart.observation_ids}
        ranked = sorted(
            (item for item in observations if item.value is not None and is_meaningful_metric(item)),
            key=lambda item: (item.id in chart_observation_ids, bool(item.evidence), item.confidence),
            reverse=True,
        )[:180]
        return [
            {
                "id": item.id,
                "metric": item.metric_canonical or item.metric_original,
                "metric_original": item.metric_original,
                "value": item.value,
                "raw_value": item.raw_value,
                "unit": item.unit,
                "raw_unit": item.raw_unit,
                "currency": item.currency,
                "period": item.period,
                "entity": item.entity,
                "dimensions": item.dimensions,
                "confidence": item.confidence,
                "source_pages": sorted({source.page for source in item.evidence}),
            }
            for item in ranked
        ]

    @staticmethod
    def _page_excerpts(
        document: ParsedDocument,
        profile: DocumentProfile,
        observations: list[Observation],
    ) -> list[dict[str, object]]:
        preferred_pages = [
            *range(1, min(document.page_count, 6) + 1),
            *profile.document_summary_pages,
            *(source.page for item in observations if item.confidence >= 0.8 for source in item.evidence),
        ]
        selected: list[int] = []
        for page_number in preferred_pages:
            if 1 <= page_number <= document.page_count and page_number not in selected:
                selected.append(page_number)
            if len(selected) >= 16:
                break
        page_by_number = {page.page_number: page for page in document.pages}
        return [
            {"page": page_number, "text": page_by_number[page_number].text[:1_600]}
            for page_number in selected
            if page_number in page_by_number and page_by_number[page_number].text.strip()
        ]
