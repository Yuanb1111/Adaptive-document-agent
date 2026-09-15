"""Dynamic report outline based on available validated findings."""

from collections import defaultdict

from adaptive_document_agent.models import DocumentProfile, Insight, ReportPlan, ReportSection
from adaptive_document_agent.services.llm import LLMGateway

from .prompting import load_prompt, untrusted_document_message


class DynamicReportPlanner:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    def plan(self, profile: DocumentProfile, insights: list[Insight]) -> ReportPlan:
        if self.gateway and insights:
            proposed = self.gateway.generate_structured(
                [
                    {"role": "system", "content": load_prompt("report_planning.txt")},
                    untrusted_document_message(str({"profile": profile.model_dump(mode="json"), "insights": [item.model_dump(mode="json", exclude={"evidence"}) for item in insights]})),
                ],
                ReportPlan,
                stage="report",
            )
            valid_ids = {item.id for item in insights}
            for section in proposed.sections:
                section.insight_ids = [identifier for identifier in section.insight_ids if identifier in valid_ids]
            proposed.sections = [section for section in proposed.sections if section.insight_ids or section.title == "Data Quality and Limitations"]
            if proposed.sections:
                return proposed
        groups: dict[str, list[str]] = defaultdict(list)
        for insight in insights:
            title = insight.title.casefold()
            if any(word in title for word in ("trend", "growth", "cagr", "change")):
                section = "Trends and Changes"
            elif any(word in title for word in ("rank", "category", "contribution", "share")):
                section = "Comparative Performance"
            elif any(word in title for word in ("correlation", "relationship")):
                section = "Relationships"
            else:
                section = "Key Analysis"
            groups[section].append(insight.id)
        sections: list[ReportSection] = []
        if insights:
            top = sorted(insights, key=lambda item: (item.importance, item.confidence), reverse=True)[:7]
            sections.append(ReportSection(title="Executive Summary", purpose="The highest-value validated findings and caveats.", insight_ids=[item.id for item in top]))
        sections.extend(ReportSection(title=title, purpose=f"Validated {title.casefold()} findings.", insight_ids=identifiers) for title, identifiers in groups.items())
        if profile.data_quality_notes:
            sections.append(ReportSection(title="Data Quality and Limitations", purpose="Extraction, OCR, evidence, and confidence limitations."))
        return ReportPlan(title=f"{profile.document_type} — Adaptive Analysis", sections=sections)
