"""Deterministic recovery for evidence-bound presentation plans.

The model is allowed to choose the story, but it must not be the only way to
produce a safe deck. This module repairs an invalid proposed plan via
PresentationPlanRepairer, and provides an evidence-only modern fallback deck
when no proposed plan can be retained.
"""

import re
from collections import defaultdict

from adaptive_document_agent.document_model import display_metric_name, sanitize_metric_for_title
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

        from adaptive_document_agent.services.company_extractor import extract_structured_company_fields, is_company_identity_resolved

        description, description_pages = self._summary_description(result)
        initial_company = CompanyProfile(
            name=result.profile.overview_title or (result.profile.document_type if result.profile.document_type != "Document" else ""),
            one_line_description=description,
            document_type=result.profile.document_type,
            source_pages=company_pages,
            field_source_pages={"one_line_description": description_pages} if description else {},
        )
        company_profile = extract_structured_company_fields(initial_company, result)
        has_identity = is_company_identity_resolved(company_profile)

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
                title="Company at a Glance" if has_identity else "Document at a Glance",
                source_pages=company_profile.source_pages or company_pages,
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
            clean_title = sanitize_metric_for_title(re.sub(r"(?i)\s+and\s+related\s+measures\b", "", group_title).strip(), max_length=48)
            clean_title = re.sub(r"(?i)\s+analysis\b", "", clean_title).strip()
            from adaptive_document_agent.services.language_qa import polish_slide_title

            slide_title = polish_slide_title(clean_title if len(clean_title.split()) >= 2 else f"{clean_title} Overview")
            slides.append(
                PresentationSlide(
                    id=f"slide_analysis_{group_index}",
                    slide_type="analysis",
                    title=slide_title,
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

        if not chart_groups and (
            result.charts
            or result.analysis_results
            or len([o for o in result.observations if o.value is not None]) >= 2
        ):
            valid_obs = [o for o in result.observations if o.value is not None and o.evidence][:6]
            obs_pages = sorted({source.page for o in valid_obs for source in o.evidence}) or company_pages
            slides.append(
                PresentationSlide(
                    id="slide_analysis_1",
                    slide_type="analysis",
                    title="Key Reported Evidence",
                    section_id="analysis_1",
                    section_title="Evidence",
                    slide_role="overview",
                    layout="single",
                    message="Evidence-backed comparison of retained reported values.",
                    observation_ids=[o.id for o in valid_obs],
                    visual_blocks=[
                        PresentationVisualBlock(
                            role="hero",
                            title="Reported Observations",
                            observation_ids=[o.id for o in valid_obs],
                        )
                    ],
                    source_pages=obs_pages,
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

        from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review
        recovered = PresentationPlanValidator().validate(
            PresentationPlan(
                title=result.report_plan.title,
                report_type="Evidence-bound document analysis",
                company=company_profile,
                slides=slides,
            ),
            result,
        )
        return stamp_editorial_review(recovered, result, origin="fallback")

    @staticmethod
    def _summary_description(result: PipelineResult) -> tuple[str, list[int]]:
        """Reuse the model's summary only with its own retained provenance.

        Profile discovery pages and summary pages serve different purposes.
        Never borrow an identity page to certify an unrelated summary. The raw
        summary stays in DocumentProfile even when unsuitable for this field.
        """
        pages = sorted(set(result.profile.document_summary_pages)
                       & set(range(1, result.document.page_count + 1)))
        if not pages:
            return "", []
        description = result.profile.document_summary.strip()
        # Citation metadata is already represented by description_pages. Strip
        # only the explicit PDF citation, never parenthetical analytical claims.
        description = re.sub(
            r"(?i)\s*\(PDF\s+pp?\.\s*\d+(?:\s*[-–—,]\s*\d+)*\)",
            "", description,
        ).strip()
        allowed = PresentationPlanValidator._allowed_company_numbers(set(pages), result)
        if PresentationPlanValidator._numbers(description) - allowed:
            return "", []
        return description, pages

    @staticmethod
    def _is_calc_artifact(text: str) -> bool:
        t = text.casefold()
        return any(
            term in t
            for term in (
                "slope",
                "intercept",
                "turning point",
                "turning_point",
                "turning points",
                "turning_points",
                "r-squared",
                "r_squared",
                "p-value",
                "residuals",
            )
        )

    def _summary_slide(self, result: PipelineResult) -> PresentationSlide:
        from adaptive_document_agent.document_model import DocumentIndex
        from adaptive_document_agent.services.pptx_export import _chart_findings, _usable_charts

        index = DocumentIndex(result.observations)
        usable = _usable_charts(result)
        findings = _chart_findings(usable, index)

        insights = sorted(
            (
                item
                for item in result.insights
                if item.evidence
                and not self._is_calc_artifact(item.title)
                and not self._is_calc_artifact(item.narrative)
            ),
            key=lambda item: (item.importance, item.confidence),
            reverse=True,
        )[:5]
        pages = sorted({source.page for item in insights for source in item.evidence})
        if not pages and usable:
            pages = sorted({p for c in usable[:3] for p in c.source_pages})

        bullets = [
            item.title
            for item in insights[:4]
            if not any(char.isdigit() for char in item.title)
        ]
        if not bullets and findings:
            bullets = [
                str(f["title"])
                for f in findings[:4]
                if not self._is_calc_artifact(str(f["title"]))
                and not self._is_calc_artifact(str(f["narrative"]))
                and not any(char.isdigit() for char in str(f["title"]))
            ]
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
        from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery

        pages = CompanyProfileDiscovery.rank_profile_pages(result.document, result.profile, max_pages=6)
        if not pages:
            pages = [page for page in result.profile.document_summary_pages if 1 <= page <= result.document.page_count]
        if not pages and result.document.page_count >= 1:
            pages = [1]
        return pages[:6]

    def _rank_charts(self, result: PipelineResult) -> list[ChartPlan]:
        task_priority = {item.id: item.priority for item in result.analysis_plan}
        task_results = {item.task_id: item for item in result.analysis_results}
        insight_text = " ".join(
            f"{item.title} {item.narrative}"
            for item in result.insights
            if item.importance >= 0.5
        ).casefold()

        focus_terms: set[str] = set()
        for f in (result.profile.analysis_focus or []):
            focus_terms.update(f.casefold().split())
        if result.profile.document_purpose:
            focus_terms.update(result.profile.document_purpose.casefold().split())
        for s in (result.report_plan.sections or []):
            focus_terms.update(s.title.casefold().split())
        focus_terms = {t for t in focus_terms if len(t) > 3}

        ranked: list[tuple[float, str, ChartPlan]] = []
        for chart in result.charts:
            observations = [item for item in result.observations if item.id in chart.observation_ids]
            if not observations:
                continue

            metric_terms = {item.metric_canonical.casefold() for item in observations if item.metric_canonical}
            metric_terms.update(item.metric_original.casefold() for item in observations if item.metric_original)

            insight_relevance = sum(1.0 for term in metric_terms if len(term) > 3 and term in insight_text)
            focus_relevance = sum(1.0 for term in metric_terms if any(t in term or term in t for t in focus_terms))

            period_count = len({item.period for item in observations if item.period})
            period_depth_score = min(period_count / 3.0, 1.5)

            numeric_values = [item.value for item in observations if item.value is not None]
            variation_score = 0.0
            if len(numeric_values) >= 2:
                distinct_vals = len(set(numeric_values))
                variation_score = 1.0 if distinct_vals > 1 else 0.2

            avg_obs_conf = sum(item.confidence for item in observations) / max(len(observations), 1)
            priority_val = float(task_priority.get(chart.analysis_task_id or "", 1))
            res_item = task_results.get(chart.analysis_task_id or "")
            t_conf = float(res_item.confidence) if res_item else 0.8
            valid_result_score = 1.0 if (res_item and res_item.result is not None and not res_item.warnings) else 0.5

            score = (
                (priority_val * 2.0)
                + (min(insight_relevance, 3.0) * 2.5)
                + (min(focus_relevance, 3.0) * 2.0)
                + (period_depth_score * 1.5)
                + (avg_obs_conf * 1.0)
                + (t_conf * 1.0)
                + (valid_result_score * 1.0)
                + (variation_score * 1.0)
                + (min(len(chart.source_pages), 5) * 0.2)
            )
            ranked.append((score, chart.id, chart))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [chart for _, _, chart in ranked[:12]]

    @staticmethod
    def _group_charts(charts: list[ChartPlan]) -> list[list[ChartPlan]]:
        remaining = list(charts)
        groups: list[list[ChartPlan]] = []
        while remaining:
            anchor = remaining.pop(0)
            group = [anchor]
            for candidate in list(remaining):
                if len(group) >= 3:
                    break
                if (
                    set(anchor.source_pages) & set(candidate.source_pages)
                    or (anchor.analysis_task_id and anchor.analysis_task_id == candidate.analysis_task_id)
                ):
                    group.append(candidate)
                    remaining.remove(candidate)
            groups.append(group)
        return groups

    @staticmethod
    def _chart_label(chart: ChartPlan, result: PipelineResult) -> str:
        observation = next((item for item in result.observations if item.id in chart.observation_ids), None)
        return display_metric_name(observation) if observation else chart.title.replace(" — Reported Values", "")
