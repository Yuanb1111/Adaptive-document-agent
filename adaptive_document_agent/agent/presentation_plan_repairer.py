"""Deterministic repairer for AI-authored presentation plans.

This module cleans and normalises proposed plans that failed validation:
it removes non-existent IDs, aligns source pages to referenced evidence,
prunes sentences with unsupported numbers, deduplicates company/risk items,
reverts invalid chart type overrides, enforces the chart count limit, fills
standard section titles, drops slides without retained evidence, and preserves
remaining valid AI slides without inventing facts.
"""

from collections import defaultdict
import re

from adaptive_document_agent.models import (
    CompanyFact,
    CompanyProfile,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    PresentationVisualBlock,
)
from adaptive_document_agent.utils.ids import stable_id
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator


class PresentationPlanRepairer:
    """Safely repair an invalid presentation plan using deterministic rules only."""

    _numeric_claim = re.compile(r"\d")
    _sentence_split = re.compile(r"(?<=[.!?。！？;；])\s+|\n+")

    def repair(self, plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
        """Prune unsupported claims, align citations, and validate the resulting plan."""
        observations = {item.id: item for item in result.observations}
        insights = {item.id: item for item in result.insights}
        charts = {item.id: item for item in result.charts}
        valid_pages = set(range(1, result.document.page_count + 1))

        cleaned_company = self._clean_company(plan.company, valid_pages)
        repaired_slides: list[PresentationSlide] = []

        for ordinal, slide in enumerate(plan.slides):
            if slide.slide_type not in {
                "cover",
                "company_overview",
                "executive_summary",
                "analysis",
                "risks",
                "data_quality",
                "appendix",
            }:
                continue

            chart_ids = self._unique([item for item in slide.chart_ids if item in charts])[:3]
            observation_ids = self._unique([item for item in slide.observation_ids if item in observations])
            insight_ids = self._unique([item for item in slide.insight_ids if item in insights])

            remaining_chart_capacity = max(0, 3 - len(chart_ids))
            blocks = [
                self._clean_block(block, observations, insights, charts, max_charts=remaining_chart_capacity)
                for block in slide.visual_blocks
            ]
            blocks = [b for b in blocks if b.chart_ids or b.observation_ids or b.insight_ids][:4]

            # Re-collect total chart IDs across slide and blocks capped at 3
            all_slide_charts: list[str] = list(chart_ids)
            for block in blocks:
                for cid in block.chart_ids:
                    if cid not in all_slide_charts and len(all_slide_charts) < 3:
                        all_slide_charts.append(cid)
                    elif cid not in all_slide_charts:
                        # Exceeded 3 charts across slide, remove from block
                        block.chart_ids = [c for c in block.chart_ids if c in all_slide_charts]

            referenced_pages = self._reference_pages(
                chart_ids, observation_ids, insight_ids, blocks, observations, insights, charts
            )

            if slide.slide_type == "company_overview":
                source_pages = (
                    sorted(set(slide.source_pages) & valid_pages)
                    if set(slide.source_pages) & valid_pages
                    else sorted(cleaned_company.source_pages or self._profile_pages(result))
                )
            elif slide.slide_type in {"executive_summary", "analysis", "risks"}:
                if referenced_pages:
                    matching = sorted(set(slide.source_pages) & referenced_pages)
                    source_pages = matching if matching else sorted(referenced_pages)
                else:
                    source_pages = sorted(set(slide.source_pages) & valid_pages)
            else:
                source_pages = sorted(set(slide.source_pages) & valid_pages)

            title = slide.title.strip() or self._default_title(slide.slide_type, ordinal)
            message = slide.message.strip()
            bullets = [item.strip() for item in slide.bullets if item.strip()]

            if slide.slide_type in {"executive_summary", "analysis", "risks"}:
                allowed_numbers = self._allowed_numbers(
                    chart_ids, observation_ids, insight_ids, blocks, observations, insights, charts
                )
                if not self._numbers_supported(title, allowed_numbers):
                    title = self._default_title(slide.slide_type, ordinal)
                message = self._clean_sentences(message, allowed_numbers)
                bullets = [item for item in bullets if self._numbers_supported(item, allowed_numbers)]

            # Drop analysis/risks slides that have zero valid evidence references
            if slide.slide_type in {"analysis", "risks"} and not (
                chart_ids or observation_ids or insight_ids or any(b.chart_ids or b.observation_ids or b.insight_ids for b in blocks)
            ):
                continue

            if slide.slide_type == "analysis" and not message:
                message = "Evidence-backed comparison of retained reported values."

            section_title = slide.section_title.strip()
            if slide.slide_type == "analysis" and not section_title:
                section_title = "Analysis"
            elif slide.slide_type == "risks" and not section_title:
                section_title = "Key watch items"
            elif slide.slide_type == "data_quality" and not section_title:
                section_title = "Data quality"
            elif slide.slide_type == "appendix" and not section_title:
                section_title = "Appendix"

            section_id = slide.section_id.strip() or (
                f"analysis_{ordinal}" if slide.slide_type == "analysis" else slide.slide_type
            )

            repaired_slides.append(
                PresentationSlide(
                    id=slide.id.strip() or stable_id("slide", slide.slide_type, ordinal),
                    slide_type=slide.slide_type,
                    title=title,
                    section_id=section_id,
                    section_title=section_title,
                    slide_role=slide.slide_role,
                    layout=slide.layout,
                    message=message,
                    bullets=bullets[:5],
                    chart_ids=chart_ids,
                    observation_ids=observation_ids,
                    insight_ids=insight_ids,
                    visual_blocks=blocks,
                    source_pages=source_pages,
                )
            )

        # Merge duplicate risks vs executive summary language
        self._deduplicate_risks_vs_summary(repaired_slides)

        ordered_plan = self._normalise_structure(
            PresentationPlan(
                title=plan.title.strip() or result.report_plan.title,
                report_type=plan.report_type.strip() or "Document analysis",
                company=cleaned_company,
                slides=repaired_slides,
            ),
            result,
        )

        return PresentationPlanValidator().validate(ordered_plan, result)

    @classmethod
    def _clean_block(
        cls,
        block: PresentationVisualBlock,
        observations: dict[str, object],
        insights: dict[str, object],
        charts: dict[str, object],
        *,
        max_charts: int = 2,
    ) -> PresentationVisualBlock:
        chart_ids = cls._unique([item for item in block.chart_ids if item in charts])[:max_charts]
        observation_ids = cls._unique([item for item in block.observation_ids if item in observations])[:12]
        insight_ids = cls._unique([item for item in block.insight_ids if item in insights])[:3]
        chart_type = block.chart_type
        if chart_type == "table":
            chart_type = None
        elif chart_type and any(
            chart_type not in {*charts[cid].available_chart_types, charts[cid].chart_type}
            for cid in chart_ids
            if cid in charts
        ):
            chart_type = None
        return PresentationVisualBlock(
            role=block.role,
            title=block.title.strip(),
            chart_ids=chart_ids,
            observation_ids=observation_ids,
            insight_ids=insight_ids,
            chart_type=chart_type,
        )

    def _clean_sentences(self, text: str, allowed: set[str]) -> str:
        if not text.strip():
            return ""
        sentences = self._sentence_split.split(text.strip())
        if len(sentences) <= 1:
            return text.strip() if self._numbers_supported(text.strip(), allowed) else ""
        valid_sentences = [s.strip() for s in sentences if s.strip() and self._numbers_supported(s.strip(), allowed)]
        return " ".join(valid_sentences)

    @classmethod
    def _clean_company(cls, company: CompanyProfile, valid_pages: set[int]) -> CompanyProfile:
        def dedupe(values: list[str]) -> list[str]:
            seen: set[str] = set()
            result: list[str] = []
            for item in values:
                norm = cls._normalized_text(item)
                if norm and norm not in seen:
                    seen.add(norm)
                    result.append(item.strip())
            return result[:6]

        facts: list[CompanyFact] = []
        seen: set[str] = set()
        for fact in company.key_facts:
            label = fact.label.strip()
            key = cls._normalized_text(label)
            if label and key not in seen:
                facts.append(
                    fact.model_copy(
                        update={
                            "label": label,
                            "value": fact.value.strip(),
                            "source_pages": sorted(set(fact.source_pages) & valid_pages),
                        }
                    )
                )
                seen.add(key)
        pages = sorted(set(company.source_pages) & valid_pages)
        has_content = any(
            (
                company.name,
                company.one_line_description,
                company.industry,
                company.headquarters,
                company.listing_market,
                company.track_record_period,
                company.business_model,
                facts,
                company.products,
                company.segments,
                company.geographies,
            )
        )
        if has_content and not (pages or any(fact.source_pages for fact in facts)):
            return CompanyProfile()
        return company.model_copy(
            update={
                "products": dedupe(company.products),
                "segments": dedupe(company.segments),
                "geographies": dedupe(company.geographies),
                "key_facts": facts[:8],
                "source_pages": pages,
            }
        )

    @classmethod
    def _deduplicate_risks_vs_summary(cls, slides: list[PresentationSlide]) -> None:
        summaries = [s for s in slides if s.slide_type == "executive_summary"]
        risks = [s for s in slides if s.slide_type == "risks"]
        if not summaries or not risks:
            return
        summary = summaries[0]
        risk = risks[0]
        summary_texts = {
            cls._normalized_text(t)
            for t in (summary.message, *summary.bullets)
            if t.strip()
        }
        # Deduplicate internal risk bullets
        deduped_bullets: list[str] = []
        seen_risk: set[str] = set()
        for b in risk.bullets:
            norm = cls._normalized_text(b)
            if norm and norm not in summary_texts and norm not in seen_risk:
                seen_risk.add(norm)
                deduped_bullets.append(b)
        risk.bullets = deduped_bullets
        if cls._normalized_text(risk.message) in summary_texts:
            risk.message = "Key areas of ongoing monitoring identified in the source materials."

    def _normalise_structure(self, plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
        """Enforce required slide order and presence of essential slides."""
        required = ("cover", "company_overview", "executive_summary")
        by_type: dict[str, list[PresentationSlide]] = defaultdict(list)
        for slide in plan.slides:
            by_type[slide.slide_type].append(slide)

        ordered: list[PresentationSlide] = []
        for slide_type in required:
            if by_type[slide_type]:
                ordered.append(by_type[slide_type][0])
            else:
                ordered.append(self._fallback_for_type(slide_type, result))

        ordered.extend(by_type["analysis"][:14])
        if by_type["risks"]:
            # Ensure risk slide has evidence
            risk_slide = by_type["risks"][0]
            if risk_slide.chart_ids or risk_slide.observation_ids or risk_slide.insight_ids or risk_slide.visual_blocks:
                ordered.append(risk_slide)

        ordered.append(
            by_type["data_quality"][0]
            if by_type["data_quality"]
            else self._fallback_for_type("data_quality", result)
        )
        ordered.append(
            by_type["appendix"][0]
            if by_type["appendix"]
            else self._fallback_for_type("appendix", result)
        )

        seen_ids: set[str] = set()
        for ordinal, slide in enumerate(ordered):
            if slide.id in seen_ids:
                slide.id = stable_id("slide", slide.slide_type, ordinal)
            seen_ids.add(slide.id)

        return plan.model_copy(update={"slides": ordered})

    def _fallback_for_type(self, slide_type: str, result: PipelineResult) -> PresentationSlide:
        pages = self._profile_pages(result)
        if slide_type == "cover":
            return PresentationSlide(id="slide_cover", slide_type="cover", title=result.report_plan.title)
        if slide_type == "company_overview":
            return PresentationSlide(
                id="slide_company_overview",
                slide_type="company_overview",
                title="Document at a Glance",
                source_pages=pages,
            )
        if slide_type == "executive_summary":
            insights = sorted(
                (item for item in result.insights if item.evidence),
                key=lambda item: (item.importance, item.confidence),
                reverse=True,
            )[:5]
            return PresentationSlide(
                id="slide_executive_summary",
                slide_type="executive_summary",
                title="Executive Summary",
                section_id="executive_summary",
                section_title="Executive summary",
                slide_role="overview",
                message="Key retained findings selected from the source document.",
                insight_ids=[item.id for item in insights],
                source_pages=sorted({source.page for item in insights for source in item.evidence}),
            )
        if slide_type == "data_quality":
            return PresentationSlide(
                id="slide_data_quality",
                slide_type="data_quality",
                title="Data Quality and Scope",
                section_id="data_quality",
                section_title="Data quality",
                slide_role="methodology",
                source_pages=pages,
            )
        return PresentationSlide(
            id="slide_appendix",
            slide_type="appendix",
            title="Source Data Appendix",
            section_id="appendix",
            section_title="Appendix",
            slide_role="source_data",
        )

    @staticmethod
    def _profile_pages(result: PipelineResult) -> list[int]:
        pages = [p for p in result.profile.document_summary_pages if 1 <= p <= result.document.page_count]
        return pages[:6]

    @classmethod
    def _reference_pages(
        cls,
        chart_ids: list[str],
        observation_ids: list[str],
        insight_ids: list[str],
        blocks: list[PresentationVisualBlock],
        observations: dict[str, object],
        insights: dict[str, object],
        charts: dict[str, object],
    ) -> set[int]:
        pages: set[int] = set()
        all_charts = {*chart_ids, *(cid for b in blocks for cid in b.chart_ids)}
        all_observations = {*observation_ids, *(oid for b in blocks for oid in b.observation_ids)}
        all_insights = {*insight_ids, *(iid for b in blocks for iid in b.insight_ids)}
        for oid in all_observations:
            if oid in observations:
                pages.update(source.page for source in observations[oid].evidence)
        for iid in all_insights:
            if iid in insights:
                pages.update(source.page for source in insights[iid].evidence)
        for cid in all_charts:
            if cid in charts:
                pages.update(charts[cid].source_pages)
                for oid in charts[cid].observation_ids:
                    if oid in observations:
                        pages.update(source.page for source in observations[oid].evidence)
        return pages

    @classmethod
    def _allowed_numbers(
        cls,
        chart_ids: list[str],
        observation_ids: list[str],
        insight_ids: list[str],
        blocks: list[PresentationVisualBlock],
        observations: dict[str, object],
        insights: dict[str, object],
        charts: dict[str, object],
    ) -> set[str]:
        all_oids = {*observation_ids, *(oid for b in blocks for oid in b.observation_ids)}
        for cid in {*chart_ids, *(c for b in blocks for c in b.chart_ids)}:
            if cid in charts:
                all_oids.update(charts[cid].observation_ids)
        text_parts = [
            str(v)
            for oid in all_oids
            if oid in observations
            for v in (
                observations[oid].value,
                observations[oid].raw_value,
                observations[oid].period,
                observations[oid].entity,
                observations[oid].dimensions,
            )
            if v is not None
        ]
        all_iids = {*insight_ids, *(iid for b in blocks for iid in b.insight_ids)}
        for iid in all_iids:
            if iid in insights:
                text_parts.extend((insights[iid].title, insights[iid].narrative))
        return PresentationPlanValidator._numbers(" ".join(text_parts))

    @classmethod
    def _numbers_supported(cls, value: str, allowed: set[str]) -> bool:
        return not cls._numeric_claim.search(value) or PresentationPlanValidator._numbers(value) <= allowed

    @classmethod
    def _unique(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @classmethod
    def _normalized_text(cls, value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9%]+", " ", value.casefold()).split())

    @staticmethod
    def _default_title(slide_type: str, ordinal: int = 0) -> str:
        return {
            "cover": "Document Analysis",
            "company_overview": "Document at a Glance",
            "executive_summary": "Executive Summary",
            "analysis": "Evidence Analysis",
            "risks": "Key Watch Items",
            "data_quality": "Data Quality and Scope",
            "appendix": "Source Data Appendix",
        }.get(slide_type, "Analysis")
