"""Select evidence-bound presentation questions before choosing any charts."""

import json

from adaptive_document_agent.models import PipelineResult, PresentationTopicSelection
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.presentation_evidence import evidence_groups
from adaptive_document_agent.utils.ids import stable_id

from .prompting import load_prompt, untrusted_document_message


def series_directory(result: PipelineResult) -> tuple[list[dict[str, object]], dict[str, list]]:
    """Expose every extracted metric scope, without truncating to a chart quota."""
    directory: list[dict[str, object]] = []
    lookup: dict[str, list] = {}
    for group in evidence_groups(result.observations):
        if not any(item.value is not None and item.evidence for item in group):
            continue
        identifier = stable_id("presentation_series", *(item.id for item in group))
        lookup[identifier] = group
        first = group[0]
        pages = sorted({e.page for item in group for e in item.evidence})
        periods = list(dict.fromkeys(item.period for item in group if item.period))
        directory.append({
            "id": identifier,
            "metric": first.metric_original,
            "canonical_metric": first.metric_canonical if first.metric_canonical != first.metric_original else None,
            "periods": periods,
            "unit": first.unit,
            "currency": first.currency,
            "entity": first.entity,
            "dimensions": {
                key: value for key, value in {**first.dimensions, **first.category_dimensions}.items()
                if key not in {"table_context", "section", "column_role"}
            },
            "source_sections": sorted({item.source_section for item in group if item.source_section}),
            "source_pages": pages,
            "observation_count": len(group),
            "first_reported_value": group[0].raw_value,
            "last_reported_value": group[-1].raw_value,
            "evidence_status": "complete" if all(item.value is not None and item.evidence and item.validation_status == "valid" for item in group) else "qualified",
        })
    return directory, lookup


class PresentationTopicSelector:
    """Ask the configured model which questions the retained evidence warrants."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def select(self, result: PipelineResult) -> PresentationTopicSelection:
        from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery

        directory, lookup = series_directory(result)
        if not directory:
            return PresentationTopicSelection()
        primary_pages = {
            page for start, end in result.profile.analysis_page_ranges
            for page in range(start, end + 1)
        }
        context_numbers = CompanyProfileDiscovery.rank_profile_pages(
            result.document, result.profile, max_pages=8
        )
        context_pages = [
            {"page": page.page_number, "text": page.text[:1600]}
            for page in result.document.pages
            if page.page_number in context_numbers
            and page.page_number not in primary_pages and page.text.strip()
        ]
        columns = (
            "id", "metric", "periods", "unit", "currency", "entity", "dimensions",
            "source_sections", "source_pages", "observation_count",
            "first_reported_value", "last_reported_value", "evidence_status",
        )
        payload = {
            "document_purpose": result.profile.document_purpose,
            "user_focus": result.profile.analysis_focus,
            "primary_analysis_ranges": result.profile.analysis_page_ranges,
            "important_sections": result.profile.important_sections,
            "series_columns": columns,
            "all_extracted_series": [[item[column] for column in columns] for item in directory],
            "validated_insights": [
                {"id": item.id, "title": item.title, "narrative": item.narrative,
                 "importance": item.importance,
                 "source_pages": sorted({e.page for e in item.evidence})}
                for item in sorted(result.insights, key=lambda item: -item.importance)[:18]
                if item.evidence
            ],
            "report_sections": [item.model_dump(mode="json") for item in result.report_plan.sections],
            "background_page_excerpts": context_pages,
        }
        messages = [
            {"role": "system", "content": load_prompt("presentation_topic_selection.txt")},
            untrusted_document_message(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        ]
        selection = self.gateway.generate_structured(
            messages,
            PresentationTopicSelection,
            stage="presentation",
        )
        try:
            self._validate(selection, lookup, primary_pages=primary_pages)
        except ValueError as exc:
            selection = self.gateway.generate_structured(
                [
                    *messages,
                    {"role": "system", "content": "Revise the topic selection to satisfy this evidence check. "
                     "Keep only exact supplied series IDs and do not add numbers. Reason: " + str(exc)},
                    untrusted_document_message(selection.model_dump_json()),
                ],
                PresentationTopicSelection,
                stage="presentation",
                allow_repair=False,
            )
            self._validate(selection, lookup, primary_pages=primary_pages)
        return selection

    @staticmethod
    def _validate(
        selection: PresentationTopicSelection,
        lookup: dict[str, list],
        *, primary_pages: set[int] | None = None,
    ) -> None:
        from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

        if lookup and not selection.topics:
            raise ValueError("No evidence-bound presentation topics were selected")
        topic_ids = [item.id for item in selection.topics]
        if len(topic_ids) != len(set(topic_ids)):
            raise ValueError("Presentation topic IDs must be unique")
        selected: set[str] = set()
        for topic in selection.topics:
            if not all((topic.id.strip(), topic.title.strip(), topic.question.strip(), topic.rationale.strip())):
                raise ValueError("Each presentation topic needs a title, question and selection reason")
            if not topic.series_ids or set(topic.series_ids) - lookup.keys():
                raise ValueError(f"Topic {topic.id} cites unknown or no metric series")
            if len(topic.series_ids) != len(set(topic.series_ids)):
                raise ValueError(f"Topic {topic.id} repeats a metric series")
            if primary_pages and any(
                not any(e.page in primary_pages for item in lookup[sid] for e in item.evidence)
                for sid in topic.series_ids
            ):
                raise ValueError(f"Topic {topic.id} uses a metric outside the primary analysis scope")
            allowed = PresentationPlanValidator._numbers(" ".join(
                str(value) for sid in topic.series_ids for item in lookup[sid]
                for value in (item.raw_value, item.value, item.period)
                if value is not None
            ))
            claimed = PresentationPlanValidator._numbers(" ".join(
                (topic.title, topic.question, topic.rationale, *topic.caveats)
            ))
            if claimed - allowed:
                raise ValueError(f"Topic {topic.id} contains unsupported numeric claims")
            selected.update(topic.series_ids)
        for omission in selection.omissions:
            if omission.series_id not in lookup or omission.series_id in selected or not omission.reason.strip():
                raise ValueError("An omission must name an unselected known series and explain why")
