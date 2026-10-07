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
    PresentationTheme,
    PresentationVisualBlock,
)
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

from .presentation_plan_repairer import PresentationPlanRepairer


class PresentationPlanRecovery:
    """Repair references via PresentationPlanRepairer, then build a safe fallback."""

    def repair(self, plan: PresentationPlan, result: PipelineResult) -> PresentationPlan:
        """Prune unsupported material and align citations via PresentationPlanRepairer."""
        return PresentationPlanRepairer().repair(plan, result)

    def recover_missing_plan(self, result: PipelineResult) -> bool:
        """Retry a missing or degraded cached compilation, retaining all QA gates.

        Commit the recovered state only when the selected questions validate.
        Failed retries leave the evidence and missing-plan export block intact.
        """
        if not result.presentation_topics or not result.presentation_topics.topics:
            return False
        from .presentation_topic_audit_recovery import recover_audited_topics
        if recover_audited_topics(result):
            return True
        previous = result.presentation_plan
        if previous is not None:
            selected = {topic.id for topic in result.presentation_topics.topics}
            covered = {theme.id for theme in previous.themes}
            degraded = previous.planning_origin in {"fallback", "topic_recovery"} or any(
                note.startswith("[review:presentation_degraded] Evidence-only fallback")
                for note in previous.editorial_notes
            )
            if not degraded:
                return False
            if selected <= covered:
                from adaptive_document_agent.validation.claim_validator import ClaimValidator
                from adaptive_document_agent.validation.presentation_provenance import insight_inputs

                problems = ClaimValidator().validate_plan(previous, result.observations, result.charts,
                                                         insight_observation_ids=insight_inputs(result))
                if not any(issue.code == "direction_scope_ambiguous" for issue in problems):
                    return False
        from .topic_plan_compiler import compile_topic_plan
        from adaptive_document_agent.models import ValidationIssue

        snapshot = result.model_copy(deep=True)
        try:
            plan = compile_topic_plan(snapshot)
            if previous is not None:
                plan.company = previous.company.model_copy(deep=True)
                PresentationPlanValidator().validate(plan, snapshot)
        except ValueError as exc:
            message = "Cached presentation recovery failed: " + str(exc)[:1400]
            if not any(i.code == "presentation_cached_recovery_failed" and i.message == message
                       for i in result.validation_warnings):
                result.validation_warnings.append(ValidationIssue(
                    code="presentation_cached_recovery_failed", severity="warning", stage="presentation",
                    message=message,
                ))
            return False
        result.presentation_plan = plan
        result.presentation_topics = snapshot.presentation_topics
        result.charts = snapshot.charts
        result.validation_warnings = snapshot.validation_warnings
        result.validation_warnings.append(ValidationIssue(
            code="presentation_cached_plan_recovered", severity="info", stage="presentation",
            message="Previously missing or degraded presentation plan recompiled from the retained model-selected questions and evidence without a model request.",
        ))
        return True

    def from_selected_topics(self, result: PipelineResult, *, origin: str = "topic_recovery") -> PresentationPlan:
        """Retain model-selected questions if final slide writing fails validation.

        The model has decided semantic relationships. This recovery only binds
        its exact series IDs to validated observations and available charts.
        """
        from .presentation_topic_selector import series_directory

        selection = result.presentation_topics
        if not selection or not selection.topics:
            raise ValueError("No selected presentation topics are available")
        # The generic fallback's chart pages are discarded below. Do not let
        # an unrelated generic chart invalidate model-selected topic recovery.
        base = self.fallback(result, validate=False)
        from .presentation_topic_scope_recovery import withheld_topic_ids, _WITHHELD_PREFIX
        if result.presentation_plan:
            # A retry for another topic cannot revive a previously withdrawn
            # takeaway, even when its shortened title equals its question.
            base.editorial_notes.extend(note for note in result.presentation_plan.editorial_notes
                                        if note.startswith(_WITHHELD_PREFIX))
        _, series_by_id = series_directory(result)
        from adaptive_document_agent.validation.topic_period_consistency import reconcile_topic_periods
        reconcile_topic_periods(result, series_by_id)
        from adaptive_document_agent.document_model import period_sort_key
        observation_by_id = {item.id: item for item in result.observations}
        from adaptive_document_agent.services.pptx_export import _usable_charts
        usable_chart_ids = {chart.id for chart in _usable_charts(result)}
        themes: list[PresentationTheme] = []
        analysis_slides: list[PresentationSlide] = []
        unavailable_topics: list[str] = []
        for topic in selection.topics:
            if any(series_id not in series_by_id for series_id in topic.series_ids):
                unavailable_topics.append(
                    f"{topic.title}: selected evidence was excluded because its source series is not reliable"
                )
                continue
            members = list(dict.fromkeys(
                item.id for sid in topic.series_ids for item in series_by_id.get(sid, [])
                if item.value is not None and item.evidence
                and item.validation_status in {"valid", "partially_valid"}
            ))
            observations = {oid: observation_by_id[oid] for oid in members if oid in observation_by_id}
            if len(observations) < 2:
                continue
            if len(topic.series_ids) > 3:
                from adaptive_document_agent.services.presentation_matrix import topic_matrix_dimension

                matrix_dimension = topic_matrix_dimension(list(observations.values()))
                if matrix_dimension:
                    pages = sorted({e.page for item in observations.values() for e in item.evidence})
                    themes.append(PresentationTheme(
                        id=topic.id, title=topic.title, question=topic.question,
                        rationale=topic.rationale, observation_ids=members,
                        caveats=topic.caveats, source_pages=pages,
                    ))
                    analysis_slides.append(PresentationSlide(
                        id=f"topic_{topic.id}", slide_type="analysis", title=topic.title,
                        section_id=topic.id, section_title=topic.title,
                        slide_role="overview", layout="data_overview", message=topic.question,
                        visual_blocks=[PresentationVisualBlock(
                            role="matrix", observation_ids=members,
                            matrix_dimension=matrix_dimension)],
                        theme_id=topic.id, analytical_question=topic.question,
                        selection_reason=topic.rationale, comparison_mode="parallel",
                        source_pages=pages,
                    ))
                    continue
            chart_ids: list[str] = []
            visible_series: set[str] = set()
            # A validated composition can cover several model-selected category
            # series together. Do not lose it by matching one series at a time.
            compositions = sorted((chart for chart in result.charts
                if chart.id in usable_chart_ids
                and chart.chart_type in {"stacked_bar", "stacked_percent", "doughnut", "pie"}
                and set(chart.observation_ids) <= observations.keys()),
                key=lambda chart: (-len(chart.observation_ids), chart.id))
            for chart in compositions:
                covered = {sid for sid in topic.series_ids
                    if {item.id for item in series_by_id.get(sid, [])} <= set([*chart.observation_ids, *chart.total_observation_ids])}
                if covered:
                    chart_ids.append(chart.id)
                    visible_series.update(covered)
                    break
            for series_id in topic.series_ids:
                if series_id in visible_series:
                    continue
                series_observation_ids = {item.id for item in series_by_id.get(series_id, [])} & observations.keys()
                matching = next((chart for chart in result.charts
                                 if chart.id in usable_chart_ids and chart.id not in chart_ids
                                 and set(chart.observation_ids) <= series_observation_ids
                                 and set(chart.observation_ids) & series_observation_ids), None)
                if matching is not None:
                    chart_ids.append(matching.id)
                    visible_series.add(series_id)
            if not chart_ids and len(members) > 40:
                # Never silently truncate a large unchartable series into a
                # purportedly complete audience analysis.
                continue
            pages = sorted({e.page for item in observations.values() for e in item.evidence})
            charted_ids = {
                oid for chart in result.charts if chart.id in chart_ids
                for oid in [*chart.observation_ids, *chart.total_observation_ids]
            }
            supporting_ids = [oid for oid in members if oid not in charted_ids]
            referenced_ids = set(supporting_ids) | charted_ids
            # Parse source fields independently: a grouped amount followed by
            # a date can otherwise absorb its year into a false numeric token.
            allowed_numbers = set().union(*(
                PresentationPlanValidator._numbers(str(value)) for oid in referenced_ids if oid in observations
                for value in (
                    observations[oid].value, observations[oid].raw_value,
                    observations[oid].period, observations[oid].entity,
                    observations[oid].dimensions,
                ) if value is not None
            ))

            def supported(text: str) -> bool:
                return not (PresentationPlanValidator._numbers(text) - allowed_numbers)

            safe_title = topic.takeaway if topic.takeaway and supported(topic.takeaway) else topic.title
            if len(safe_title.split()) > 18 and supported(topic.title):
                safe_title = topic.title
            if not supported(safe_title):
                safe_title = topic.question if supported(topic.question) else "Selected evidence"
            safe_question = topic.question if supported(topic.question) else "How do the cited measures compare?"
            safe_reason = topic.rationale if supported(topic.rationale) else ""
            # Retain selected evidence that cannot form a chart in the
            # supporting band, with every source point available in notes.
            visible_support_ids: list[str] = []
            for series_id in topic.series_ids:
                series_items = sorted(
                    (item for item in series_by_id.get(series_id, []) if item.id in supporting_ids),
                    key=lambda item: period_sort_key(item.period),
                )
                if series_items:
                    visible_support_ids.extend(item.id for item in series_items)
            visible_support_ids = list(dict.fromkeys(visible_support_ids))
            theme = PresentationTheme(
                id=topic.id, title=topic.title, question=topic.question,
                rationale=topic.rationale, chart_ids=chart_ids,
                observation_ids=members, caveats=topic.caveats,
                source_pages=pages,
            )
            themes.append(theme)
            paginate = len(chart_ids) > 3 or len(supporting_ids) > 40
            if not paginate:
                groups = [(chart_ids, supporting_ids)]
            else:
                from adaptive_document_agent.services.presentation_display_plan import balanced_groups
                groups = [(group, []) for group in balanced_groups(chart_ids)]
                groups += [([], visible_support_ids[start:start + 12])
                           for start in range(0, len(visible_support_ids), 12)]
            for part, (group, support) in enumerate(groups):
                # Each continuation cites only its displayed evidence. A global
                # takeaway cannot borrow numbers from another panel's scope.
                local_ids = set(support) | {
                    oid for chart in result.charts if chart.id in group
                    for oid in [*chart.observation_ids, *chart.total_observation_ids]}
                local_pages = sorted({e.page for oid in local_ids if oid in observation_by_id
                                      for e in observation_by_id[oid].evidence})
                from adaptive_document_agent.validation.topic_period_consistency import continuation_copy
                local_question, local_reason = continuation_copy(safe_question, safe_reason,
                    [observation_by_id[oid] for oid in sorted(local_ids) if oid in observation_by_id])
                analysis_slides.append(PresentationSlide(
                    id=f"topic_{topic.id}" if part == 0 else f"topic_{topic.id}_part_{part + 1}",
                    slide_type="analysis", title=local_question if paginate else safe_title,
                    section_id=topic.id, section_title=topic.title,
                    slide_role="overview" if part == 0 else "deep_dive",
                    layout="three_up" if len(group) == 3 else "two_up" if len(group) == 2
                           else "chart_with_data" if group and support else "single" if group else "data_overview",
                    message=local_question, chart_ids=group, observation_ids=support,
                    visual_blocks=[PresentationVisualBlock(role="table", observation_ids=support[start:start + 12])
                                   for start in range(0, len(support), 12)],
                    theme_id=topic.id, analytical_question=local_question,
                    selection_reason=local_reason, comparison_mode="parallel" if len(group) > 1 else "context",
                    source_pages=local_pages,
                ))
        if not analysis_slides:
            raise ValueError("Selected presentation topics contain no usable analytical evidence")
        base.themes = themes
        base.coverage_notes = [
            f"{series_by_id[item.series_id][0].metric_original}: {item.reason}"
            for item in selection.omissions if item.series_id in series_by_id
        ] + unavailable_topics
        linked_metrics = set()
        for theme in themes:
            for oid in theme.observation_ids:
                item = observation_by_id.get(oid)
                if item is None:
                    continue
                categories = item.category_dimensions or {
                    key: value for key, value in item.dimensions.items()
                    if key not in {"table_context", "section", "period_basis", "column_role"}
                }
                label = item.metric_original.strip()
                if categories:
                    linked_metrics.add((label + " (" + ", ".join(str(v) for _, v in sorted(categories.items())) + ")").casefold())
                else:
                    linked_metrics.add(label.casefold())
        topic_insight_ids = {
            item.id for item in result.insights
            if item.metric and item.metric.strip().casefold() in linked_metrics
        }
        selected_observation_ids = {oid for theme in themes for oid in theme.observation_ids}
        inputs_by_task = {
            item.task_id: set(item.input_observation_ids)
            for item in result.analysis_results
        }
        topic_insight_ids.update(
            item.id for item in result.insights
            if any(inputs_by_task.get(task_id) and inputs_by_task[task_id] <= selected_observation_ids
                   for task_id in item.result_ids)
        )
        # Evidence volume and duplicate sources must not reorder or omit the
        # model's selected questions. The summary renderer handles pagination.
        from .presentation_summary_selection import rebuild_selected_topic_summary
        rebuild_selected_topic_summary(result, base)
        closing = self._risks_slide(
            result, base.slides[2], allowed_insight_ids=topic_insight_ids,
            include_summary_insights=True,
            topic_observation_groups=[set(theme.observation_ids) for theme in themes],
        )
        base.slides = [
            *base.slides[:3], *analysis_slides,
            *([closing] if closing else []),
            *(slide for slide in base.slides if slide.slide_type in {"data_quality", "appendix"}),
        ]
        withheld = withheld_topic_ids(base)
        for slide in base.slides:
            if slide.slide_type == "analysis" and slide.theme_id in withheld:
                slide.title = slide.analytical_question
        rebuild_selected_topic_summary(result, base)
        from adaptive_document_agent.services.presentation_claim_evidence import prepare_presentation_claims
        prepare_presentation_claims(result, base)
        from .presentation_topic_scope_recovery import validate_selected_topic_claims
        base = validate_selected_topic_claims(base, result)
        from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review
        return stamp_editorial_review(PresentationPlanValidator().validate(base, result), result, origin=origin)

    def fallback(self, result: PipelineResult, *, validate: bool = True) -> PresentationPlan:
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
        if has_identity and re.search(
            r"(?i)\b(?:unnamed\s+(?:issuer|company)|(?:issuer|company)\s+name\s+(?:is\s+)?(?:not\s+(?:stated|provided|disclosed)|unavailable))\b",
            company_profile.one_line_description,
        ):
            # A scoped discovery summary cannot contradict a sourced identity.
            company_profile.one_line_description = ""
            company_profile.field_source_pages.pop("one_line_description", None)
        cover_title = result.report_plan.title
        if has_identity and re.search(r"(?i)\bunnamed\s+(?:\w+\s+){0,3}(?:issuer|company|prospectus)\b", cover_title):
            cover_title = f"{company_profile.name}: {result.profile.document_type}"

        summary_slide = self._summary_slide(result)
        slides: list[PresentationSlide] = [
            PresentationSlide(
                id="slide_cover",
                slide_type="cover",
                title=cover_title,
                message=result.profile.document_purpose or "Evidence-bound document intelligence analysis",
            ),
            PresentationSlide(
                id="slide_company_overview",
                slide_type="company_overview",
                title="Company at a Glance" if has_identity else "Document at a Glance",
                source_pages=company_profile.source_pages or company_pages,
            ),
            summary_slide,
        ]

        # Thematic analysis slides with context-aware grouping
        chart_groups = _group_chart_plans(charts[:10], index) if charts else []
        for group_index, group in enumerate(chart_groups, start=1):
            chart_ids = [item.id for item in group]
            pages = sorted({page for item in group for page in item.source_pages})
            obs_first = next((index.get(oid) for oid in group[0].observation_ids if index.get(oid)), None)
            first_label = self._audience_label(obs_first) if obs_first else self._chart_label(group[0], result)
            group_title = _chart_group_title(group, index)
            layout = "single" if len(group) == 1 else "two_up" if len(group) == 2 else "three_up"
            blocks = [
                PresentationVisualBlock(
                    role="hero" if idx == 0 else "supporting",
                    title=self._audience_label(next((index.get(oid) for oid in chart.observation_ids if index.get(oid)), None)) or self._chart_label(chart, result),
                    chart_ids=[chart.id],
                )
                for idx, chart in enumerate(group)
            ]
            clean_title = re.sub(r"(?i)\s+and\s+related\s+measures\b", "", group_title).strip()
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
        risk_slide = self._risks_slide(result, summary_slide)
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

        recovered = PresentationPlan(
            title=result.report_plan.title,
            report_type="Evidence-bound document analysis",
            company=company_profile,
            slides=slides,
        )
        if not validate:
            return recovered
        from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review
        recovered = PresentationPlanValidator().validate(recovered, result)
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
    def _risks_slide(
        cls, result: PipelineResult, summary: PresentationSlide,
        *, allowed_insight_ids: set[str] | None = None,
        include_summary_insights: bool = False,
        topic_observation_groups: list[set[str]] | None = None,
    ) -> PresentationSlide | None:
        """Close with sourced implications and monitoring points, not metric names."""
        summary_ids = set(summary.insight_ids)
        normalize = lambda value: re.sub(r"[\W_]+", " ", value.casefold()).strip()
        summary_copy = {normalize(value) for value in (summary.message, *summary.bullets) if value.strip()}
        eligible = [
            item for item in result.insights
            if item.evidence
            and (allowed_insight_ids is None or item.id in allowed_insight_ids)
            and (include_summary_insights or item.id not in summary_ids)
            and (include_summary_insights or normalize(item.title) not in summary_copy)
        ]
        eligible.sort(key=lambda item: (item.importance, item.confidence), reverse=True)
        bullets: list[str] = []
        selected_ids: list[str] = []
        pages: set[int] = set()
        # Validate findings and optional monitoring points independently before
        # selecting the most informative closing copy.
        groups = []
        seen = set(summary_copy)
        from adaptive_document_agent.validation.claim_validator import ClaimValidator
        from adaptive_document_agent.validation.presentation_provenance import insight_inputs
        from adaptive_document_agent.validation.scoped_narrative_values import scoped_value_errors
        from adaptive_document_agent.models import ValidationIssue
        import json

        links = insight_inputs(result)
        by_id = {o.id: o for o in result.observations}
        for field in ("implication", "watch_item"):
            candidates = []
            for item in eligible:
                # A calculated finding has a verified, numeric narrative. Its
                # optional implication may assert that other evidence is absent
                # without a document-wide proof of absence.
                statement = ((item.narrative if field == "implication" and item.kind == "calculated_result"
                              else getattr(item, field)) or "").strip()
                if (not statement or (field == "watch_item" and any(char.isdigit() for char in statement))
                    or re.search(r"(?i)\b(?:caused|driven by|due to|contributed to)\b", statement)
                    or normalize(statement) in seen):
                    continue
                # Optional closing copy must pass on its own analysis inputs.
                # An unsafe conclusion cannot invalidate every selected topic
                # or borrow another bullet's dates and values. Keep the model's
                # original statement and rejection in the audit and raw insight.
                records = [by_id[oid] for oid in links.get(item.id, [])]
                candidate = PresentationSlide(id="slide_risks", slide_type="risks", title="Conclusions",
                    bullets=[statement], observation_ids=[o.id for o in records])
                failures = [issue.message for issue in ClaimValidator().validate_slide(candidate, records)
                            if issue.severity == "error"]
                failures.extend(scoped_value_errors(candidate, records, result.observations))
                if failures:
                    audit = json.dumps({"insight_id": item.id, "field": field,
                        "statement": statement, "errors": failures}, ensure_ascii=False, sort_keys=True)
                    if not any(issue.code == "presentation_closing_claim_withheld" and issue.message == audit
                               for issue in result.validation_warnings):
                        result.validation_warnings.append(ValidationIssue(
                            code="presentation_closing_claim_withheld", severity="warning", stage="presentation",
                            message=audit, related_ids=[item.id, *links.get(item.id, [])], evidence=item.evidence,
                        ))
                    continue
                seen.add(normalize(statement))
                candidates.append((item, statement))
            groups.append(candidates)
        # Lead with validated findings. A generic monitoring sentence must not
        # displace an already verified outcome just to fill a watch-item quota.
        if topic_observation_groups:
            # Preserve model priority while giving distinct model-selected
            # questions a representative conclusion before repeated findings
            # on one question consume the closing capacity.
            covered = set()
            representatives, repeated = [], []
            for item, statement in groups[0]:
                inputs = set(links.get(item.id, []))
                memberships = {i for i, ids in enumerate(topic_observation_groups) if inputs & ids}
                if memberships - covered:
                    representatives.append((item, statement))
                    covered.update(memberships)
                else:
                    repeated.append((item, statement))
            groups[0] = representatives + repeated
        ordered = groups[0] + groups[1]
        has_watch_item = any(candidate in groups[1] for candidate in ordered[:4])
        for item, statement in ordered[:4]:
            bullets.append(statement)
            selected_ids.append(item.id)
            pages.update(source.page for source in item.evidence)
        if not bullets:
            return None
        return PresentationSlide(
            id="slide_risks",
            slide_type="risks",
            title="Conclusions and Watch Items" if has_watch_item else "Conclusions",
            section_id="risks",
            section_title="Conclusions",
            slide_role="risk",
            message=("Implications and indicators to monitor, based on the cited findings."
                     if has_watch_item else "Conclusions based on the cited findings."),
            bullets=bullets,
            observation_ids=list(dict.fromkeys(oid for iid in selected_ids for oid in links.get(iid, []))),
            bullet_observation_ids=([links[iid] for iid in selected_ids]
                                   if all(links.get(iid) for iid in selected_ids) else []),
            insight_ids=list(dict.fromkeys(selected_ids)),
            source_pages=sorted(pages),
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
    def _audience_label(observation) -> str:
        """Remove source footnote markers from prose, retaining raw evidence."""
        label = display_metric_name(observation) if observation else ""
        label = re.sub(r"(?<=[A-Za-z])\(\d{1,2}\)(?=\s|$)", "", label)
        if observation:
            category = observation.category_dimensions.get("category") or observation.dimensions.get("category")
            if category and category.casefold() not in label.casefold():
                label = f"{label}: {category}"
        return label

    @staticmethod
    def _chart_label(chart: ChartPlan, result: PipelineResult) -> str:
        observation = next((item for item in result.observations if item.id in chart.observation_ids), None)
        return display_metric_name(observation) if observation else chart.title.replace(" — Reported Values", "")
