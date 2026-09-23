"""AI analyst that selects and organises an evidence-bound slide narrative."""

import json

from adaptive_document_agent.document_model import is_meaningful_metric
from adaptive_document_agent.models import ChartPlan, DocumentProfile, Observation, ParsedDocument, PipelineResult, PresentationPlan
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

from .presentation_plan_repairer import PresentationPlanRepairer
from .prompting import load_prompt, untrusted_document_message


class PresentationPlanner:
    """Use the configured model to write a story plan without changing facts."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def plan(self, result: PipelineResult) -> PresentationPlan:
        from adaptive_document_agent.services.presentation_evidence import build_evidence_catalog, observation_record
        # Keep the semantic planning context focused. Large PDFs can contain
        # thousands of observations; an oversized catalogue makes it harder
        # for the model to organise a coherent story even when it fits its
        # nominal context window. Chart observations remain available below.
        catalog = build_evidence_catalog(
            result,
            max_series=30,
            max_observations=130,
            max_source_pages=8,
            max_calculations=90,
        )
        catalog_ids = {o["id"] for o in catalog["observations"]}
        chart_ids = {oid for c in result.charts for oid in [*c.observation_ids, *c.total_observation_ids]}
        payload = {
            "document_profile": result.profile.model_dump(mode="json"),
            "document_page_count": result.document.page_count,
            "page_excerpts": self._page_excerpts(result.document, result.profile, result.observations),
            "observations": catalog.pop("observations"),
            "evidence_catalog": catalog,
            "chart_observations": [observation_record(o) for o in result.observations if o.id in chart_ids - catalog_ids],
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
        messages = [
            {"role": "system", "content": load_prompt("presentation_planning.txt")},
            untrusted_document_message(json.dumps(payload, ensure_ascii=False)),
        ]
        proposed = self.gateway.generate_structured(
            messages,
            PresentationPlan,
            stage="presentation",
        )
        validator = PresentationPlanValidator()
        from adaptive_document_agent.services.presentation_editorial import review_presentation, stamp_editorial_review
        # Status is assigned here, never trusted from the structured response.
        proposed.planning_origin = "model"
        safe_original = None
        try:
            validator.validate(proposed, result)
            safe_original = proposed.model_copy(deep=True)
            editorial = review_presentation(proposed, result)
            if editorial:
                raise ValueError("Presentation editorial review: " + " ".join(
                    f"{item.slide_id or 'deck'}: {item.message}" for item in editorial
                ))
            return stamp_editorial_review(proposed, result, origin="model")
        except ValueError as exc:
            model_repair_error = ""
            candidate = proposed
            try:
                candidate = self.gateway.generate_structured(
                    [
                        *messages,
                        {
                            "role": "system",
                            "content": (
                                "The prior presentation plan failed deterministic validation. "
                                "Correct only the cited problems and return the complete schema again. "
                                "Do not add facts, numbers, IDs, or source pages. Validation feedback: "
                                + str(exc)
                            ),
                        },
                        untrusted_document_message(
                            json.dumps({"prior_plan": proposed.model_dump(mode="json")}, ensure_ascii=False)
                        ),
                    ],
                    PresentationPlan,
                    stage="presentation",
                    allow_repair=False,
                )
                return stamp_editorial_review(validator.validate(candidate, result), result, origin="repaired")
            except Exception as repair_exc:
                # The deterministic recovery is deliberately narrower than a model repair:
                # it can only remove unreferenced material and align citations.
                model_repair_error = str(repair_exc)
            if safe_original is not None:
                # A failed style revision must not discard a previously valid
                # analytical plan or downgrade it to metric-by-metric recovery.
                retained = stamp_editorial_review(safe_original, result, origin="model")
                retained.editorial_notes.append("Editorial revision could not be retained; the evidence-validated original plan remains available for review.")
                return retained
            try:
                return stamp_editorial_review(PresentationPlanRepairer().repair(candidate, result), result, origin="repaired")
            except ValueError as deterministic_exc:
                raise ValueError(
                    "Presentation plan validation failed. Initial reason: "
                    f"{exc}. AI repair reason: {model_repair_error}. "
                    f"Deterministic repair reason: {deterministic_exc}"
                ) from deterministic_exc

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
        from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery

        company_discovery_pages = CompanyProfileDiscovery.rank_profile_pages(document, profile, max_pages=6)
        preferred_pages = [
            *range(1, min(document.page_count, 4) + 1),
            *company_discovery_pages,
            *profile.document_summary_pages,
            *(source.page for item in observations if item.confidence >= 0.8 for source in item.evidence),
        ]
        selected: list[int] = []
        for page_number in preferred_pages:
            if 1 <= page_number <= document.page_count and page_number not in selected:
                selected.append(page_number)
            if len(selected) >= 12:
                break
        page_by_number = {page.page_number: page for page in document.pages}
        return [
            {"page": page_number, "text": page_by_number[page_number].text[:3_200 if page_number in company_discovery_pages else 1_600]}
            for page_number in selected
            if page_number in page_by_number and page_by_number[page_number].text.strip()
        ]
