"""Deterministic recovery for evidence-bound presentation plans.

The model is allowed to choose the story, but it must not be the only way to
produce a safe deck. This module repairs an invalid proposed plan via
PresentationPlanRepairer, and provides an evidence-only modern fallback deck
when no proposed plan can be retained.
"""

from collections import defaultdict

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.models import (
    ChartPlan,
    CompanyProfile,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    PresentationVisualBlock,
)
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

from .presentation_plan_repairer import PresentationPlanRepairer


class PresentationPlanRecovery:
    """Repair references via PresentationPlanRepairer, then build a safe fallback."""

    def repair(self, plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
        """Prune unsupported material and align citations via PresentationPlanRepairer."""
        return PresentationPlanRepairer().repair(plan, result)

    def fallback(self, result: PipelineResult) -> PresentationPlan:
        """Build a modern, evidence-only deck when no AI plan can be validated.

        Base structure:
        1. Cover
        2. Company at a Glance
        3. Contents (rendered dynamically from generated sections)
        4. Executive Summary (verified insights and findings)
        5+. Thematic analysis slides
        6. Key Risks (generated only if verified risk evidence exists)
        7. Data Quality
        8+. Appendix
        """
        from adaptive_document_agent.document_model import DocumentIndex
        from adaptive_document_agent.services.pptx_export import _chart_group_title, _group_chart_plans, _usable_charts

        company_pages = self._profile_pages(result)
        usable = _usable_charts(result)
        index = DocumentIndex(result.observations)
        ranked = self._rank_charts(result)
        charts = [c for c in ranked if c.id in {item.id for item in usable}]
        if not charts:
            charts = usable[:10]

        company_profile = CompanyProfile(
            name=result.profile.overview_title or (result.profile.document_type if result.profile.document_type != "Document" else "Document Overview"),
            one_line_description=result.profile.document_summary or result.profile.document_purpose,
            document_type=result.profile.document_type,
            source_pages=company_pages,
        )

        slides: list[PresentationSlide] = [
            PresentationSlide(
                id="slide_cover",
                slide_type="cover",
                title=result.report_plan.title,
                message=result.profile.document_purpose or "Evidence-bound document intelligence analysis",
            ),
            PresentationSlide(
                id="slide_company_overview",
                slide_type="company_overview",
                title="Company at a Glance" if result.profile.overview_title else "Document at a Glance",
                source_pages=company_pages,
            ),
            self._summary_slide(result),
        ]

        # Thematic analysis slides with context-aware grouping
        chart_groups = _group_chart_plans(charts[:10], index) if charts else []
        for group_index, group in enumerate(chart_groups, start=1):
            chart_ids = [item.id for item in group]
            pages = sorted({page for item in group for page in item.source_pages})
            obs_first = next((index.get(oid) for oid in group[0].observation_ids if index.get(oid)), None)
            first_label = display_metric_name(obs_first) if obs_first else self._chart_label(group[0], result)
            group_title = _chart_group_title(group, index)
            layout = "single" if len(group) == 1 else "two_up" if len(group) == 2 else "three_up"
            blocks = [
                PresentationVisualBlock(
                    role="hero" if idx == 0 else "supporting",
                    title=display_metric_name(next((index.get(oid) for oid in chart.observation_ids if index.get(oid)), None)) or self._chart_label(chart, result),
                    chart_ids=[chart.id],
                )
                for idx, chart in enumerate(group)
            ]
            slides.append(
                PresentationSlide(
                    id=f"slide_analysis_{group_index}",
                    slide_type="analysis",
                    title=f"{group_title} analysis" if not group_title.casefold().endswith("analysis") else group_title,
                    section_id=f"analysis_{group_index}",
                    section_title=first_label,
                    slide_role="overview" if group_index == 1 else "deep_dive",
                    layout=layout,
                    message="Evidence-backed comparison of retained reported values.",
                    chart_ids=chart_ids,
                    visual_blocks=blocks,
                    source_pages=pages,
                )
            )

        # Key Risks: only generated if risk evidence exists
        risk_slide = self._risks_slide(result)
        if risk_slide:
            slides.append(risk_slide)

        slides.extend(
            [
                PresentationSlide(
                    id="slide_data_quality",
                    slide_type="data_quality",
                    title="Data Quality and Scope",
                    section_id="data_quality",
                    section_title="Data quality",
                    slide_role="methodology",
                    source_pages=company_pages,
                ),
                PresentationSlide(
                    id="slide_appendix",
                    slide_type="appendix",
                    title="Source Data Appendix",
                    section_id="appendix",
                    section_title="Appendix",
                    slide_role="source_data",
                    source_pages=sorted({page for chart in charts for page in chart.source_pages}),
                ),
            ]
        )

        return PresentationPlanValidator().validate(
            PresentationPlan(
                title=result.report_plan.title,
                report_type="Evidence-bound document analysis",
                company=company_profile,
                slides=slides,
            ),
            result,
        )

    def _summary_slide(self, result: PipelineResult) -> PresentationSlide:
        from adaptive_document_agent.document_model import DocumentIndex
        from adaptive_document_agent.services.pptx_export import _chart_findings, _usable_charts

        index = DocumentIndex(result.observations)
        usable = _usable_charts(result)
        findings = _chart_findings(usable, index)

        insights = sorted(
            (item for item in result.insights if item.evidence),
            key=lambda item: (item.importance, item.confidence),
            reverse=True,
        )[:5]
        pages = sorted({source.page for item in insights for source in item.evidence})
        if not pages and usable:
            pages = sorted({p for c in usable[:3] for p in c.source_pages})

        bullets = [item.title for item in insights[:4] if not any(char.isdigit() for char in item.title)]
        if not bullets and findings:
            bullets = [str(f["title"]) for f in findings[:4] if not any(char.isdigit() for char in str(f["title"]))]
        if not bullets:
            bullets = ["Key retained findings selected from the source document."]

        return PresentationSlide(
            id="slide_executive_summary",
            slide_type="executive_summary",
            title="Executive Summary",
            section_id="executive_summary",
            section_title="Executive summary",
            slide_role="overview",
            message="Key retained findings selected from the source document.",
            bullets=bullets,
            insight_ids=[item.id for item in insights],
            source_pages=pages,
        )

    @classmethod
    def _risks_slide(cls, result: PipelineResult) -> PresentationSlide | None:
        """Generate a risks slide only when explicit, evidenced risks exist."""
        risk_terms = ("risk", "anomaly", "watch", "limitation", "decline", "negative", "loss", "uncertainty")
        risk_insights = [
            item for item in result.insights
            if item.evidence and (
                item.kind in {"risk", "anomaly", "limitation"}
                or any(term in item.title.casefold() or term in item.narrative.casefold() for term in risk_terms)
            )
        ]
        if not risk_insights:
            return None
        risk_insights = sorted(risk_insights, key=lambda item: (item.importance, item.confidence), reverse=True)[:4]
        pages = sorted({source.page for item in risk_insights for source in item.evidence})
        bullets = [item.title for item in risk_insights if not any(char.isdigit() for char in item.title)][:4]
        return PresentationSlide(
            id="slide_risks",
            slide_type="risks",
            title="Key Risks and Watch Items",
            section_id="risks",
            section_title="Key risks",
            slide_role="risk",
            message="Evidence-backed risk indicators and areas of operational or financial monitoring.",
            bullets=bullets,
            insight_ids=[item.id for item in risk_insights],
            source_pages=pages,
        )

    @staticmethod
    def _profile_pages(result: PipelineResult) -> list[int]:
        pages = [page for page in result.profile.document_summary_pages if 1 <= page <= result.document.page_count]
        return pages[:6]

    def _rank_charts(self, result: PipelineResult) -> list[ChartPlan]:
        task_priority = {item.id: item.priority for item in result.analysis_plan}
        insight_text = " ".join(f"{item.title} {item.narrative}" for item in result.insights if item.importance >= 0.6).casefold()
        ranked: list[tuple[tuple[float, ...], ChartPlan]] = []
        for chart in result.charts:
            observations = [item for item in result.observations if item.id in chart.observation_ids]
            metric_terms = {item.metric_canonical.casefold() for item in observations if item.metric_canonical}
            metric_terms.update(item.metric_original.casefold() for item in observations if item.metric_original)
            semantic_relevance = sum(1 for term in metric_terms if len(term) > 3 and term in insight_text)
            period_count = len({item.period for item in observations if item.period})
            # Multi-period depth bonus
            period_depth = 2.0 if period_count >= 3 else 1.0 if period_count == 2 else 0.0
            # Peripheral penalty for low-explanatory items
            peripheral_penalty = 0.0
            for term in metric_terms:
                if any(p in term for p in ("prepaid", "deposit", "other payable", "miscellaneous", "stamp duty")):
                    peripheral_penalty -= 2.0
            score = (
                float(task_priority.get(chart.analysis_task_id or "", 0)),
                float(semantic_relevance),
                period_depth,
                sum(item.confidence for item in observations) / max(len(observations), 1),
                float(len(chart.source_pages)),
                peripheral_penalty,
            )
            ranked.append((score, chart))
        return [chart for _, chart in sorted(ranked, key=lambda item: (item[0], item[1].id), reverse=True)[:12]]

    @staticmethod
    def _group_charts(charts: list[ChartPlan]) -> list[list[ChartPlan]]:
        return [charts[index : index + 3] for index in range(0, len(charts), 3)]

    @staticmethod
    def _chart_label(chart: ChartPlan, result: PipelineResult) -> str:
        observation = next((item for item in result.observations if item.id in chart.observation_ids), None)
        return display_metric_name(observation) if observation else chart.title.replace(" — Reported Values", "")
