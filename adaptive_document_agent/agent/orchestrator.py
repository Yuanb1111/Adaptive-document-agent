"""End-to-end pipeline; UI and providers depend on this stable API."""

from collections.abc import Callable
from contextlib import ExitStack, nullcontext
from typing import BinaryIO

from adaptive_document_agent.document_model import DocumentIndex, DocumentModelBuilder
from adaptive_document_agent.extraction.chart_extractor import ChartExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.pdf_parser import PDFParser
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.extraction.vision_adapter import VisionAdapter
from adaptive_document_agent.models import AnalysisResult, AnalysisScopePreview, AnalysisTask, DocumentProfile, Observation, ParsedDocument, PipelineResult, ValidationIssue
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.models.customization import PresentationBudget
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.timing import record_timing
from adaptive_document_agent.validation import CalculationValidator, ConsistencyChecker, CoverageValidator, EvidenceValidator, ExtractionValidator, SemanticValidator
from adaptive_document_agent.validation.report_validator import ReportValidator

from .analysis_planner import AnalysisPlanner
from .candidate_generator import AnalysisCandidateGenerator
from .introduction_checkpoint import (IntroductionGuardedGateway, IntroductionVerificationFailed,
                                      failed_introduction_result)
from .chart_planner import ChartPlanner
from .document_discovery import DocumentDiscovery
from .executor import AnalysisExecutor
from .insight_generator import InsightGenerator
from .presentation_planner import PresentationPlanner
from .presentation_plan_recovery import PresentationPlanRecovery
from .presentation_topic_selector import PresentationTopicSelector, series_directory
from .report_generator import ReportGenerator
from .report_planner import DynamicReportPlanner
from .semantic_resolver import SemanticResolver
from .value_scorer import AnalysisValueScorer

ProgressCallback = Callable[[str], None]


class DocumentOrchestrator:
    """Analyse one PDF with optional semantic LLM stages and local caching."""

    def __init__(self, gateway: LLMGateway | None = None, *, cache: DiskCache | None = None) -> None:
        self.gateway = gateway
        self.cache = cache
        if gateway is not None:
            gateway.cache = cache

    def analyse_pdf(
        self,
        file: bytes | bytearray | BinaryIO,
        settings: object | None = None,
        *,
        progress: ProgressCallback | None = None,
        analysis_focus: str | None = None,
        scope: AnalysisScopePreview | None = None,
        resume: PipelineResult | None = None,
        presentation_budget: PresentationBudget | None = None,
    ) -> PipelineResult:
        # All background work belongs to this invocation, never to the reusable
        # orchestrator/session. ExitStack also drains it on any primary failure.
        from adaptive_document_agent.services.presentation_requirements import fixed_presentation_budget
        presentation_budget = fixed_presentation_budget(presentation_budget)
        with ExitStack() as resources:
            return self._analyse_pdf(
                file, settings, progress=progress, analysis_focus=analysis_focus,
                scope=scope, resume=resume, presentation_budget=presentation_budget, resources=resources,
            )

    def _analyse_pdf(
        self,
        file: bytes | bytearray | BinaryIO,
        settings: object | None = None,
        *,
        progress: ProgressCallback | None = None,
        analysis_focus: str | None = None,
        scope: AnalysisScopePreview | None = None,
        resume: PipelineResult | None = None,
        presentation_budget: PresentationBudget | None = None,
        resources: ExitStack,
    ) -> PipelineResult:
        del settings  # Configuration is enforced when constructing the gateway.
        notify = progress or (lambda _: None)
        from time import perf_counter
        pipeline_started = perf_counter()
        timings: dict[str, int] = {}
        details: dict[str, int] = {}
        raw = bytes(file) if isinstance(file, (bytes, bytearray)) else file.read()
        digest = sha256_bytes(raw)

        if resume is not None:
            from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
            if (resume.pipeline_version != PIPELINE_VERSION or resume.document.sha256 != digest
                    or resume.pipeline_state != 'partial' or resume.retry_from is None
                    or any(p.table_extraction_status == 'failed' for p in resume.document.pages)):
                raise ValueError('Retry checkpoint does not match this analysis or has incomplete extraction.')
            # Validate the uploaded bytes before reusing any derived content.
            self._load_document(raw, digest)
            document = resume.document.model_copy(deep=True)
            if scope and (scope.document_sha256 != digest or scope.page_count != document.page_count):
                raise ValueError('The confirmed analysis scope does not belong to this PDF.')
            profile = resume.profile.model_copy(deep=True)
            if presentation_budget is not None:
                from adaptive_document_agent.services.slide_budgets import resolved_limits
                if (presentation_budget.body_slides not in resolved_limits(profile.report_requirements,
                        section='report', scope=presentation_budget.slide_scope) or
                    min(presentation_budget.body_slides, presentation_budget.introduction_slides)
                        not in resolved_limits(profile.report_requirements, section='introduction', scope=presentation_budget.slide_scope) or
                    presentation_budget.analysis_slides not in resolved_limits(profile.report_requirements,
                        section='analysis', scope=presentation_budget.slide_scope)):
                    raise ValueError('Retry presentation budget differs from the saved request; start a new analysis.')
            requirements = profile.report_requirements
            analysis_focus = profile.analysis_focus
            from .source_coverage import retry_failed_source_checks
            with record_timing(details, 'retry_source_checks'):
                retry_failed_source_checks(document, profile, self.gateway, progress=notify)
            observations = [o.model_copy(deep=True) for o in resume.observations]
            extractor = ObservationExtractor()
            index = DocumentModelBuilder().build(observations)
            from .company_introduction import prepare_company_introduction
            attach_introduction = resources.enter_context(prepare_company_introduction(
                self.gateway, PipelineResult(document=document, profile=profile,
                    presentation_plan=(resume.presentation_plan.model_copy(deep=True)
                        if resume.retry_from == 'reporting' and resume.presentation_plan else None)),
                timings=details))
            notify('Retrying introduction with retained extraction and calculations')
        else:
            notify("Reading PDF")
            with record_timing(timings, "pdf_ingestion"):
                document = self._load_document(raw, digest)
            if scope and (scope.document_sha256 != digest or scope.page_count != document.page_count):
                raise ValueError("The confirmed analysis scope does not belong to this PDF.")

            from .report_requirements import interpret_requirements, appendix_pages
            original_instructions = analysis_focus or ''
            requirements = None
            if analysis_focus and analysis_focus.strip():
                notify('Interpreting analysis and presentation requirements')
                with record_timing(timings, 'report_requirements'):
                    requirements = interpret_requirements(self.gateway, document, analysis_focus)
                if not requirements.interpretation_error:
                    analysis_focus = '; '.join(r.request_quote for r in requirements.items
                        if r.resolution == 'resolved' and r.kind == 'analysis_focus') or None
            if presentation_budget is not None:
                from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget
                requirements = apply_presentation_budget(requirements, original_instructions, presentation_budget)

            notify("Understanding document")
            with record_timing(timings, "document_discovery"):
                profile = DocumentDiscovery(self.gateway, cache=self.cache).discover(
                    document,
                    analysis_focus=analysis_focus,
                    progress=notify,
                    routed_ranges=scope.page_ranges if scope else None,
                    enable_source_checks=True,
                    confirmed_scope=scope is not None,
                )

            from .company_introduction import prepare_company_introduction
            if requirements is not None:
                profile.report_requirements = requirements
                profile.analysis_focus = analysis_focus
                for requirement in requirements.items:
                    notify('Report requirement: ' + requirement.description)
            attach_introduction = None
            if self.gateway and self.gateway.discovery_workers > 1:
                # Discovery is the earliest stable source/profile boundary. Copy it
                # before table extraction/recovery can mutate or replace document.
                attach_introduction = resources.enter_context(prepare_company_introduction(
                    self.gateway, PipelineResult(document=document, profile=profile), timings=details,
                ))

            notify("Extracting tables from selected sections")
            with record_timing(timings, "table_extraction"):
                page_numbers = (
                    {page for start, end in profile.analysis_page_ranges for page in range(start, end + 1)}
                    if profile.analysis_page_ranges
                    else None
                )
                if page_numbers is not None:
                    page_numbers |= appendix_pages(profile.report_requirements)
                scope = sha256_bytes(str(sorted(page_numbers) if page_numbers is not None else 'all').encode('utf-8'))[:16]
                from adaptive_document_agent.utils.pipeline_version import EXTRACTION_VERSION
                cached_tables = self.cache.get_model(f"tables-{EXTRACTION_VERSION}-{digest}-{scope}", ParsedDocument) if self.cache else None
                if cached_tables is not None and any(page.table_extraction_status != 'processed'
                        for page in cached_tables.pages if page_numbers is None or page.page_number in page_numbers):
                    cached_tables = None
                if cached_tables is not None:
                    document = cached_tables
                else:
                    table_extractor = TableExtractor()
                    tables_by_page = table_extractor.extract(raw, page_numbers=page_numbers)
                    raw_tables_by_page = getattr(table_extractor, 'raw_tables_by_page', tables_by_page)
                    for page in document.pages:
                        page.tables = tables_by_page.get(page.page_number, [])
                        page.raw_tables = [t.model_copy(deep=True) for t in raw_tables_by_page.get(page.page_number, [])]
                        page.source_table_inventory = getattr(table_extractor,'source_inventory_by_page',{}).get(page.page_number,{})
                        if page_numbers is None or page.page_number in page_numbers:
                            page.table_extraction_status = ('processed' if page.page_number in tables_by_page else 'failed')
                            if page.table_extraction_status == 'failed':
                                warning = f'Table extraction failed on page {page.page_number}; later pages were still processed.'
                                if warning not in page.warnings:
                                    page.warnings.append(warning)
                                if warning not in document.warnings:
                                    document.warnings.append(warning)
                    self._reconstruct_tables(document)
                    if self.cache and all(page.table_extraction_status == 'processed' for page in document.pages
                                          if page_numbers is None or page.page_number in page_numbers):
                        self.cache.set_model(f"tables-{EXTRACTION_VERSION}-{digest}-{scope}", document)

            notify("Extracting structured observations")
            with record_timing(timings, "observation_extraction"):
                extractor = ObservationExtractor()
                observations = extractor.extract(document, page_ranges=profile.analysis_page_ranges)
                mappings = SemanticResolver(self.gateway).resolve_metrics(
                    [item.metric_original for item in observations],
                    context="\n".join(page.text[:2_000] for page in document.pages)[:12_000],
                )
                mapping_by_name = {item.original_name: item for item in mappings}
                for observation in observations:
                    mapping = mapping_by_name.get(observation.metric_original)
                    if mapping and mapping.confidence >= 0.7:
                        observation.metric_canonical = mapping.canonical_name

            notify("Normalizing financial data layer")
            with record_timing(timings, "financial_normalization"):
                from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer

                observations = FinancialNormalizer.normalize_observations(observations)

            notify("Building document model")
            with record_timing(timings, "document_model"):
                index = DocumentModelBuilder().build(observations)

        if resume is not None and resume.retry_from == 'reporting':
            candidates, scores = resume.candidates, resume.candidate_scores
            plan, results = resume.analysis_plan, resume.analysis_results
            issues = self._validate_analysis(profile, observations, results)
            # A report retry can reuse only source-bound completed audit batches.
            # Their own fingerprint and final target-partition checks remain
            # mandatory after fresh topic selection; no stale approval is assumed.
            audit_checkpoint = next((issue for issue in reversed(resume.validation_warnings)
                if issue.code in {'report_audit_scope_review', 'report_audit_scope_unresolved'}), None)
            if audit_checkpoint is not None:
                issues.append(audit_checkpoint.model_copy(deep=True))
        else:
            notify("Generating analysis candidates")
            if attach_introduction is not None and attach_introduction.failed():
                return failed_introduction_result(attach_introduction,
                    PipelineResult(document=document, profile=profile, observations=index.observations,
                        validation_warnings=self._validate_analysis(profile, observations, [])),
                    self.gateway, resources, timings, details, pipeline_started, notify,
                    before_scoring=True)
            with record_timing(timings, "candidate_generation"):
                candidates = AnalysisCandidateGenerator().generate(index, profile)
                scores = AnalysisValueScorer(self.gateway).score(candidates, index, profile, progress=notify,
                    reserved_workers=int(attach_introduction is not None
                        and attach_introduction.background_running()))

            notify("Selecting useful analyses")
            with record_timing(timings, "analysis_planning"):
                plan = AnalysisPlanner().plan(scores, index)

            notify("Reusing extracted evidence for selected analyses")
            with record_timing(timings, "targeted_extraction"):
                # The broad extraction above already visits every table/text row in
                # the confirmed scope. extract(required_metrics=...) only filters
                # that same output, then _merge_observations discards its duplicate
                # IDs. Reuse the enriched index; missing inputs remain validator errors.
                # A genuine sparse-evidence recovery below still re-extracts after
                # reconstructing new tables, so no new source evidence is skipped.
                pass

            notify("Running deterministic calculations")
            with record_timing(timings, "execution"):
                results = AnalysisExecutor().execute(plan, index)

            notify("Checking consistency and validating results")
            with record_timing(timings, "validation"):
                issues = self._validate_analysis(profile, observations, results)

        selected_pages = [
            page
            for page in document.pages
            if not profile.analysis_page_ranges or any(start <= page.page_number <= end for start, end in profile.analysis_page_ranges)
        ]
        with record_timing(timings, 'source_chart_inventory'):
            candidates_images = ChartExtractor().candidates(selected_pages)
        if candidates_images and self.gateway:
            vision_warning = VisionAdapter(self.gateway).unavailable_message()
            if vision_warning:
                profile.data_quality_notes.append(vision_warning)
        elif candidates_images:
            profile.data_quality_notes.append("Chart candidates were detected; no vision model is configured.")

        if attach_introduction is not None and attach_introduction.failed():
            return failed_introduction_result(attach_introduction,
                PipelineResult(document=document, profile=profile, observations=index.observations,
                    candidates=candidates, candidate_scores=scores, analysis_plan=plan,
                    analysis_results=results, validation_warnings=issues),
                self.gateway, resources, timings, details, pipeline_started, notify)

        checkpoint = PipelineResult(document=document, profile=profile, observations=index.observations,
            candidates=candidates, candidate_scores=scores, analysis_plan=plan,
            analysis_results=results, validation_warnings=issues)
        editorial_gateway = (IntroductionGuardedGateway(self.gateway, attach_introduction)
                             if attach_introduction is not None else self.gateway)
        try:
            if isinstance(editorial_gateway, IntroductionGuardedGateway):
                editorial_gateway.check()
            notify("Generating insights and dynamic report")
            with record_timing(timings, "reporting"):
                reporting = self._generate_report(document, profile, index, plan, results, issues, notify, analysis_focus,
                    gateway=editorial_gateway, output=checkpoint)
                details.update(reporting.stage_details_ms)
                if isinstance(editorial_gateway, IntroductionGuardedGateway):
                    editorial_gateway.check()
                insights, report_plan = reporting.insights, reporting.report_plan
                topic_selection, charts = reporting.presentation_topics, reporting.charts
                markdown, issues = reporting.report_markdown, reporting.validation_warnings

                # Structured diagnostic metadata logging
                import logging
                import re
                logger = logging.getLogger("adaptive_document_agent.pipeline")
                raw_obs_count = len(observations)
                valid_obs_count = sum(1 for o in observations if getattr(o, "validation_status", "valid") == "valid")
                partial_obs_count = sum(1 for o in observations if getattr(o, "validation_status", "") == "partially_valid")
                retained_count = len(index.observations)
                metric_series_count = len(index.metrics())
                chartable_series_count = len(charts)
                selected_insight_count = len(insights)
            
                logger.info(
                    "Extraction & Analysis Pipeline Diagnostics: "
                    "raw_observation_count=%d, valid_count=%d, partial_count=%d, "
                    "retained_count=%d, metric_series_count=%d, chartable_series_count=%d, selected_insight_count=%d",
                    raw_obs_count, valid_obs_count, partial_obs_count,
                    retained_count, metric_series_count, chartable_series_count, selected_insight_count,
                )

                # Minimum evidence sanity check & recovery pass:
                # If narrative layer identifies quantitative trends but structured evidence is sparse or charts == 0
                quantitative_claim_count = sum(
                    len(re.findall(r"\b\d+(?:\.\d+)?%?\b", f"{ins.title} {ins.narrative}"))
                    for ins in insights
                )
                if (not charts or len(index.observations) < 4) and (quantitative_claim_count >= 2 or len(insights) >= 2):
                    notify("Evidence unexpectedly sparse; triggering multi-strategy extraction recovery pass")
                    from adaptive_document_agent.extraction.borderless_table_extractor import BorderlessTableExtractor
                    from adaptive_document_agent.extraction.table_candidate_selector import TableCandidateSelector
                    from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer

                    # 1. Run multiple extraction strategies across relevant pages and select/merge best candidates
                    reconstructor = TableReconstructor()
                    for p in selected_pages:
                        reconstructed = [reconstructor.reconstruct(t) for t in p.tables] if p.tables else []
                        borderless = BorderlessTableExtractor().extract(p, p.page_number)
                        borderless_reconstructed = [reconstructor.reconstruct(t) for t in borderless] if borderless else []

                        if reconstructed and borderless_reconstructed:
                            p.tables = TableCandidateSelector.merge_or_replace_tables(reconstructed, borderless_reconstructed)
                        elif borderless_reconstructed:
                            p.tables = borderless_reconstructed
                        elif reconstructed:
                            p.tables = reconstructed
                    self._reconstruct_tables(document)

                    # 2. Re-extract the selected scope, including vertical text fallback.
                    recovered = extractor.extract(document, page_ranges=profile.analysis_page_ranges or None)
                    if recovered:
                        recovered = FinancialNormalizer.normalize_observations(recovered)
                        merged = self._merge_observations(observations, recovered)
                        # No new evidence means no downstream state changed. Avoid
                        # repeating paid semantic stages for identical recovery output.
                        if len(merged) > len(observations):
                            observations = merged
                            index = DocumentModelBuilder().build(observations)
                            notify("Recalculating and validating recovered evidence")
                            candidates = AnalysisCandidateGenerator().generate(index, profile)
                            scores = AnalysisValueScorer(editorial_gateway).score(candidates, index, profile,
                                reserved_workers=int(attach_introduction is not None
                                    and attach_introduction.background_running()))
                            plan = AnalysisPlanner().plan(scores, index)
                            results = AnalysisExecutor().execute(plan, index)
                            # Replace stale validation and report artifacts together.
                            # Fresh topic selection must bind to the rebuilt series.
                            issues = self._validate_analysis(profile, observations, results)
                            checkpoint.observations = index.observations
                            checkpoint.candidates, checkpoint.candidate_scores = candidates, scores
                            checkpoint.analysis_plan, checkpoint.analysis_results = plan, results
                            reporting = self._generate_report(
                                document, profile, index, plan, results, issues, notify, analysis_focus,
                                gateway=editorial_gateway, output=checkpoint,
                            )
                            details.update({f"recovery_{name}": value for name, value in reporting.stage_details_ms.items()})
                            insights, report_plan = reporting.insights, reporting.report_plan
                            topic_selection, charts = reporting.presentation_topics, reporting.charts
                            markdown, issues = reporting.report_markdown, reporting.validation_warnings

                # 4. Diagnostics when charts == 0
                if not charts:
                    diag_summary, failure_reasons = self._diagnose_zero_charts(document, observations, index)
                    logger.warning("Zero charts planned diagnostics:\n%s", diag_summary)
                    issues.append(
                        ValidationIssue(
                            code="CHARTS_ZERO_DIAGNOSTIC",
                            severity="warning",
                            message=diag_summary,
                            stage="chart_planning",
                        )
                    )
                    notify(f"Diagnostics: 0 charts retained. {len(index.metrics())} metrics found; {len(failure_reasons)} candidate series failed chartability.")

            prepared_brief = None
            deferred_brief = False

            presentation_plan = None
            if self.gateway:
                notify("Planning presentation narrative")
                with record_timing(timings, "presentation_planning"):
                    planning_result = PipelineResult(
                        document=document,
                        profile=profile,
                        observations=index.observations,
                        candidates=candidates,
                        candidate_scores=scores,
                        analysis_plan=plan,
                        analysis_results=results,
                        insights=insights,
                        report_plan=report_plan,
                        report_markdown=markdown,
                        charts=charts,
                        presentation_topics=topic_selection,
                        validation_warnings=issues,
                    )
                    checkpoint = planning_result
                    if editorial_gateway is not None and isinstance(editorial_gateway, IntroductionGuardedGateway):
                        editorial_gateway.check()
                    # Serial/local clients retain their existing request order.
                    with (nullcontext(attach_introduction) if attach_introduction is not None
                          else prepare_company_introduction(self.gateway, planning_result,
                                                            timings=details)) as attach_introduction:
                        editorial_gateway = IntroductionGuardedGateway(self.gateway, attach_introduction)
                        editorial_gateway.check()
                        def prepare_stable_topic_brief(current, compiled):
                            nonlocal prepared_brief, deferred_brief
                            if prepared_brief is not None:
                                raise RuntimeError('Executive briefing was already prepared for this run')
                            from .prepared_executive_brief import prepare_executive_brief
                            # The compiler and scoped wording repair have finished.
                            # Identity is attached only on the caller, and its source
                            # snapshot cannot be mutated by later visual planning.
                            checkpoint.presentation_plan = compiled.model_copy(deep=True)
                            from .brief_budget_schedule import briefing_waits_for_budget
                            if briefing_waits_for_budget(current, compiled):
                                deferred_brief = True
                                return
                            seed = current.model_copy(deep=True)
                            seed.presentation_plan = compiled.model_copy(deep=True)
                            from .report_audit_scope import needs_report_audit_scope
                            if needs_report_audit_scope(seed):
                                deferred_brief = True
                                return
                            try:
                                with record_timing(timings, 'brief_identity_wait'):
                                    attach_introduction(seed.presentation_plan, seed)
                            except (LLMResponseError, ValueError) as exc:
                                raise IntroductionVerificationFailed(str(exc)) from exc
                            from .brief_budget_schedule import native_briefing_waits_for_budget
                            if native_briefing_waits_for_budget(seed, seed.presentation_plan):
                                deferred_brief = True
                                return
                            prepared_brief = resources.enter_context(
                                prepare_executive_brief(editorial_gateway, seed, timings=details))

                        topics_ready = (prepare_stable_topic_brief
                            if self.gateway.discovery_workers > 1 and topic_selection and topic_selection.topics
                            else None)
                        try:
                            with record_timing(details, "slide_plan"):
                                presentation_plan = PresentationPlanner(
                                    editorial_gateway, on_topics_ready=topics_ready).plan(planning_result)
                        except (LLMResponseError, ValueError) as exc:
                            detail = " ".join(str(exc).split())[:1_400]
                            issues.append(
                                ValidationIssue(
                                    code="presentation_plan_failed",
                                    message=(
                                        "The AI presentation plan could not be retained. "
                                        f"Reason: {detail or 'No additional validation detail was available.'}"
                                    ),
                                    severity="warning",
                                    stage="presentation",
                                )
                            )
                            try:
                                recovery = PresentationPlanRecovery()
                                if topic_selection and topic_selection.topics:
                                    try:
                                        presentation_plan = recovery.from_selected_topics(planning_result)
                                    except ValueError as topic_exc:
                                        issues.append(ValidationIssue(
                                            code="presentation_topic_recovery_failed",
                                            message="Selected questions could not form a validated presentation: "
                                                    + " ".join(str(topic_exc).split())[:800],
                                            severity="warning", stage="presentation",
                                        ))
                                if presentation_plan is None:
                                    presentation_plan = recovery.fallback(planning_result)
                                issues.append(
                                    ValidationIssue(
                                        code="presentation_plan_fallback",
                                        message="A validated question-first or evidence-only presentation plan was generated in place of the invalid AI slide plan.",
                                        severity="info",
                                        stage="presentation",
                                    )
                                )
                            except Exception as fallback_exc:
                                presentation_plan = None
                                issues.append(
                                    ValidationIssue(
                                        code="presentation_plan_fallback_failed",
                                        message=f"Fallback presentation plan could not be generated: {fallback_exc}",
                                        severity="error",
                                        stage="presentation",
                                    )
                                )

                        if presentation_plan:
                            checkpoint.presentation_plan = presentation_plan
                            try:
                                with record_timing(details, "company_introduction_wait"):
                                    attach_introduction(presentation_plan, planning_result)
                            except (LLMResponseError, ValueError) as exc:
                                raise IntroductionVerificationFailed(str(exc)) from exc
                    editorial_gateway.check()
                    if presentation_plan is None:
                        # No eventual consumer remains. Stop before another optional
                        # introduction request while the executive brief is written.
                        attach_introduction.close()
                        # An optional plan failure intentionally cancels introduction
                        # work; that cancellation is not a mandatory failure.
                        editorial_gateway = self.gateway
                    # Pydantic owns a separate warning list on this snapshot. Keep
                    # local recovery's original drafts and evidence decisions in
                    # the final JSON instead of losing them after planning.
                    recorded_issues = {issue.model_dump_json() for issue in issues}
                    for issue in planning_result.validation_warnings:
                        if issue.model_dump_json() not in recorded_issues:
                            issues.append(issue)
                            recorded_issues.add(issue.model_dump_json())
                    if presentation_plan:
                        from adaptive_document_agent.validation.claim_validator import repair_presentation_plan
                        from adaptive_document_agent.validation.cross_slide_validator import CrossSlideValidator

                        from adaptive_document_agent.validation.presentation_provenance import insight_inputs
                        insight_refs = insight_inputs(planning_result)
                        presentation_plan, plan_repairs = repair_presentation_plan(presentation_plan, index.observations, charts,
                            insight_observation_ids=insight_refs)
                        for repair_msg in plan_repairs:
                            issues.append(
                                ValidationIssue(
                                    code="claim_contradiction_repaired",
                                    message=repair_msg,
                                    severity="info",
                                    stage="presentation",
                                )
                            )
                        cross_val = CrossSlideValidator(presentation_plan, index.observations, charts,
                            insight_observation_ids=insight_refs)
                        cross_issues = cross_val.validate_and_repair(auto_repair=True)
                        for c_issue in cross_issues:
                            issues.append(
                                ValidationIssue(
                                    code=c_issue.code,
                                    message=c_issue.message,
                                    severity="info" if c_issue.severity == "INFO" else ("error" if c_issue.severity == "CRITICAL" else "warning"),
                                    stage="presentation",
                                )
                            )

            checkpoint.presentation_plan = presentation_plan
            executive_brief = None
            from .brief_budget_schedule import native_briefing_waits_for_budget
            from .report_audit_scope import defer_brief_for_audit
            audit_deferred = defer_brief_for_audit(checkpoint, prepared_brief)
            if audit_deferred:
                deferred_brief = True
                prepared_brief = None
            if prepared_brief is None and not deferred_brief:
                deferred_brief = native_briefing_waits_for_budget(checkpoint, presentation_plan)
            if self.gateway and audit_deferred:
                issues.append(ValidationIssue(code='executive_brief_deferred_to_audit',
                    stage='report', severity='info', message=
                    'Deferred the final briefing until measure-specific audit scope is reviewed. '
                    'Any earlier parallel draft is discarded and its worker is drained.'))
            elif self.gateway and deferred_brief:
                issues.append(ValidationIssue(code='executive_brief_deferred_to_budget',
                    stage='report', severity='info', message=
                    'The selected draft already exceeds a slide limit. Deferred the briefing until '
                    'model-owned physical selection is stable, avoiding a disposable first briefing.'))
            if self.gateway and not deferred_brief:
                notify("Writing the evidence-bound executive briefing")
                from .prepared_executive_brief import current_executive_brief
                with record_timing(timings, "executive_brief"):
                    snapshot = PipelineResult(document=document, profile=profile,
                        observations=index.observations, insights=insights, analysis_results=results,
                        presentation_plan=presentation_plan, presentation_topics=topic_selection)
                    try:
                        executive_brief = current_executive_brief(editorial_gateway, snapshot, prepared_brief)
                    except (LLMResponseError, ValueError) as exc:
                        issues.append(ValidationIssue(code="executive_brief_unavailable", stage="report",
                            severity="warning", message="The final briefing could not be source-checked: " + str(exc)[:500]))
                    finally:
                        details.update(snapshot.stage_details_ms)
                        # Brief repairs keep their original/patch evidence audit on
                        # this separate snapshot, including rejected recoveries.
                        recorded_issues = {issue.model_dump_json() for issue in issues}
                        for issue in snapshot.validation_warnings:
                            if issue.model_dump_json() not in recorded_issues:
                                issues.append(issue)
                                recorded_issues.add(issue.model_dump_json())

        except IntroductionVerificationFailed as exc:
            # Pydantic may copy the planning warning list. Keep failures already
            # recorded by local recovery alongside the snapshot's own audits.
            recorded_issues = {issue.model_dump_json() for issue in checkpoint.validation_warnings}
            for issue in issues:
                if issue.model_dump_json() not in recorded_issues:
                    checkpoint.validation_warnings.append(issue)
                    recorded_issues.add(issue.model_dump_json())
            details.update(checkpoint.stage_details_ms)
            return failed_introduction_result(attach_introduction, checkpoint, self.gateway, resources,
                timings, details, pipeline_started, notify, failure=exc,
                skipped='remaining editorial requests, briefing and localization.')

        # Include cancellation/drain in wall time and capture all worker usage.
        # In particular, a missing/valid final plan may never have awaited it.
        with record_timing(timings, 'background_drain'):
            resources.close()
        from .source_coverage import link_coverage
        link_coverage(profile.source_coverage, index.observations, presentation_plan)
        from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
        final_result = PipelineResult(
            pipeline_version=PIPELINE_VERSION,
            executive_brief=executive_brief,
            document=document,
            profile=profile,
            observations=index.observations,
            candidates=candidates,
            candidate_scores=scores,
            analysis_plan=plan,
            analysis_results=results,
            insights=insights,
            report_plan=report_plan,
            presentation_plan=presentation_plan,
            report_markdown=markdown,
            charts=charts,
            presentation_topics=topic_selection,
            validation_warnings=issues,
            llm_usage=list(self.gateway.usage) if self.gateway else [],
            timings_ms=timings,
            stage_details_ms=details,
            pipeline_total_ms=int((perf_counter() - pipeline_started) * 1000),
        )
        from adaptive_document_agent.services.pipeline_completion import (
            is_complete, is_reporting_ready, require_source_integration, require_topic_coverage)
        if self.gateway and is_reporting_ready(final_result):
            from .presentation_budget_refinement import refine_presentation_budget, FinalBudgetBriefError
            final_stage = 'presentation_coverage'
            try:
                require_topic_coverage(final_result)
                final_stage = 'report_audit_scope'
                from .report_audit_scope import review_report_audit_scope
                with record_timing(final_result.stage_details_ms, 'report_audit_scope'):
                    review_report_audit_scope(self.gateway, final_result, progress=notify)
                final_stage = 'presentation_budget'
                with record_timing(final_result.stage_details_ms, 'physical_presentation_budget'):
                    refine_presentation_budget(self.gateway,final_result,progress=notify)
                    final_stage = 'report_audit_scope'
                    from .report_audit_scope import require_report_audit_scope
                    require_report_audit_scope(final_result)
                    final_stage = 'presentation_budget'
                    if deferred_brief:
                        from .brief_budget_schedule import complete_deferred_brief
                        complete_deferred_brief(self.gateway, final_result, progress=notify)
                if final_result.executive_brief is None and any(
                        issue.code == 'executive_brief_unavailable' for issue in final_result.validation_warnings):
                    final_stage = 'executive_brief'
                    reason = next(issue.message for issue in reversed(final_result.validation_warnings)
                                  if issue.code == 'executive_brief_unavailable')
                    raise ValueError(reason)
                final_stage = 'source_integration'
                original_brief = final_result.executive_brief
                if original_brief is not None:
                    from .source_integration_review import review_supplementary_sources
                    with record_timing(final_result.stage_details_ms, 'source_integration_review'):
                        final_result.executive_brief = review_supplementary_sources(
                            self.gateway, final_result, original_brief, progress=notify)
                require_source_integration(final_result)
                final_stage = 'presentation_coverage'
                require_topic_coverage(final_result)
                final_stage = 'presentation_budget'
                if final_result.executive_brief != original_brief:
                    from .presentation_budget_refinement import measure
                    from adaptive_document_agent.services.slide_budgets import require_exported_budgets
                    deck, _ = measure(final_result)
                    require_exported_budgets(deck, final_result)
            except (ValueError, LLMResponseError, FinalBudgetBriefError) as exc:
                final_result.pipeline_state = 'partial'
                final_result.retry_from = 'reporting'
                final_result.failed_stage = final_stage
                final_result.failure_details = dict(component=(
                    'ExecutiveBrief' if final_stage == 'executive_brief' else
                    'SourceIntegration' if final_stage == 'source_integration' else
                    'ReportAuditScope' if final_stage == 'report_audit_scope' else
                    'PresentationCoverage' if final_stage == 'presentation_coverage' else 'PresentationBudget'),
                    error_type=type(exc).__name__, message=str(exc))
                final_result.validation_warnings.append(ValidationIssue(code=(
                    'executive_brief_failed' if final_stage == 'executive_brief'
                    else 'source_integration_failed' if final_stage == 'source_integration'
                    else 'report_audit_scope_failed' if final_stage == 'report_audit_scope'
                    else 'presentation_coverage_failed' if final_stage == 'presentation_coverage'
                    else 'presentation_physical_budget_failed'), severity='warning',
                    stage='report' if final_stage in {'source_integration', 'executive_brief'} else 'presentation', message=str(exc)))
        if not is_complete(final_result):
            final_result.pipeline_state = 'partial'
            final_result.retry_from = 'reporting'
            resources.close()
            final_result.llm_usage = list(self.gateway.usage) if self.gateway else []
            final_result.timings_ms = dict(timings)
            final_result.pipeline_total_ms = int((perf_counter() - pipeline_started) * 1000)
            final_result.stage_details_ms['foreground_uninstrumented'] = max(0,
                final_result.pipeline_total_ms - sum(timings.values())
                - final_result.stage_details_ms.get('physical_presentation_budget', 0))
            notify('Analysis incomplete; diagnostics and retry checkpoint retained')
            return final_result
        notify("Complete")
        from .report_localization import prepare_report_language
        from adaptive_document_agent.services.customization_checks import check_requirements
        with record_timing(timings, 'customization_review'):
            if profile.report_requirements:
                from .requirements_review import review_content_requirements
                notify('Checking requested report customizations')
                with record_timing(final_result.stage_details_ms, 'content_requirement_review'):
                    review_content_requirements(self.gateway, final_result)
            # Source-language fallback applies even without custom instructions.
            with record_timing(final_result.stage_details_ms, 'report_localization'):
                prepare_report_language(self.gateway, final_result, progress=notify)
            if final_result.profile.report_requirements:
                with record_timing(final_result.stage_details_ms, 'customization_checks'):
                    check_requirements(final_result)
        final_result.llm_usage = list(self.gateway.usage) if self.gateway else []
        # Pydantic copies input dictionaries. Timings recorded after constructing
        # the result must be explicitly synchronized, including the 90% phase.
        final_result.timings_ms = dict(timings)
        if presentation_plan and presentation_plan.company.summary_review:
            final_result.stage_details_ms.update({'company_introduction_' + key: value
                for key, value in presentation_plan.company.summary_review.timings_ms.items()})
        final_result.pipeline_total_ms = int((perf_counter() - pipeline_started) * 1000)
        # Stage details overlap by design. Account for the remaining foreground
        # work without pretending every nested/background time is additive.
        final_result.stage_details_ms['foreground_uninstrumented'] = max(0,
            final_result.pipeline_total_ms - sum(timings.values())
            - final_result.stage_details_ms.get('physical_presentation_budget', 0))
        final_result.stage_details_ms['brief_identity_wait'] = timings.get('brief_identity_wait', 0)
        return final_result

    @staticmethod
    def _validate_analysis(
        profile: DocumentProfile, observations: list[Observation], results: list[AnalysisResult],
    ) -> list[ValidationIssue]:
        """Validate the current snapshot, including evidence recovered after a first pass."""
        issues: list[ValidationIssue] = []
        for validator, values in (
            (ExtractionValidator(), observations),
            (SemanticValidator(), observations),
            (ConsistencyChecker(), observations),
            (CoverageValidator(profile), observations),
            (CalculationValidator(), results),
            (EvidenceValidator(), results),
        ):
            issues.extend(validator.validate(values).issues)  # type: ignore[arg-type]
        return issues

    def _generate_report(
        self, document: ParsedDocument, profile: DocumentProfile, index: DocumentIndex,
        plan: list[AnalysisTask], results: list[AnalysisResult], issues: list[ValidationIssue],
        notify: ProgressCallback, analysis_focus: str | None, *,
        gateway=None, output: PipelineResult | None = None,
    ) -> PipelineResult:
        """Build all reporting artifacts from one validated analysis snapshot."""
        from .output_planning import plan_outputs
        from adaptive_document_agent.extraction.source_header_scope import source_header_issues

        gateway = self.gateway if gateway is None else gateway
        output = output if output is not None else PipelineResult(document=document, profile=profile,
            observations=index.observations, analysis_plan=plan, analysis_results=results)
        issues = list(issues)
        output.validation_warnings = issues
        for issue in source_header_issues(document):
            if issue not in issues:
                issues.append(issue)
        details = output.stage_details_ms
        with record_timing(details, "insights"):
            insight_generator = InsightGenerator(gateway)
            insights = insight_generator.generate(results, index.observations, document=document)
            issues.extend(insight_generator.validation_issues)
        notify("Selecting presentation questions before chart generation")
        output.insights = insights
        report_plan, topic_selection, topic_error = plan_outputs(gateway, output, timings=details, progress=notify)
        output.report_plan, output.presentation_topics = report_plan, topic_selection
        if isinstance(gateway, IntroductionGuardedGateway):
            gateway.check()
        # Scoped topic corrections retain their complete rejected drafts and
        # validation errors on the reporting snapshot, including partial success.
        issues.extend(issue for issue in output.validation_warnings if issue not in issues)
        requested_series = []
        if topic_selection is not None:
            _, series_by_id = series_directory(output)
            requested_series = [
                series_by_id[series_id]
                for topic in topic_selection.topics for series_id in topic.series_ids
            ]
        if topic_error is not None:
            issues.append(ValidationIssue(
                code="presentation_topic_selection_failed",
                message="Question-first presentation selection was unavailable: "
                        + " ".join(str(topic_error).split())[:800],
                severity="warning", stage="presentation",
            ))
        notify('Generating charts from selected presentation questions')
        charts = ChartPlanner().plan(
            plan, results, index, preferred_metrics=profile.metrics, insights=insights,
            report_plan=report_plan, analysis_focus=analysis_focus,
            requested_series=requested_series,
            only_requested=bool(topic_selection and topic_selection.topics),
        )
        markdown = ReportGenerator().generate(
            profile, report_plan, insights, issues, observations=index.observations, charts=charts,
        )
        issues.extend(ReportValidator().validate(markdown, results).issues)
        output.report_plan = report_plan
        output.presentation_topics = topic_selection
        output.charts = charts
        output.report_markdown = markdown
        output.validation_warnings = issues
        output.stage_details_ms = details
        return output

    def preview_scope(
        self,
        file: bytes | bytearray | BinaryIO,
        *,
        analysis_focus: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> AnalysisScopePreview:
        """Route a PDF to reviewable page ranges without running deep analysis."""
        notify = progress or (lambda _: None)
        raw = bytes(file) if isinstance(file, (bytes, bytearray)) else file.read()
        digest = sha256_bytes(raw)
        notify("Reading PDF page map")
        document = self._load_document(raw, digest)
        notify("Selecting evidence-bearing page ranges")
        ranges = DocumentDiscovery(self.gateway).route(document, analysis_focus)
        pages = {
            page
            for item in ranges
            for page in range(item.start_page, item.end_page + 1)
            if 1 <= page <= document.page_count
        }
        notify("Analysis scope ready for confirmation")
        return AnalysisScopePreview(
            document_id=document.document_id,
            document_sha256=digest,
            page_count=document.page_count,
            selected_page_count=len(pages),
            page_ranges=ranges,
        )

    def _load_document(self, raw: bytes, digest: str) -> ParsedDocument:
        document = self.cache.get_model(f"document-v4-{digest}", ParsedDocument) if self.cache else None
        if document is None:
            document = PDFParser().parse(raw, extract_tables=False)
            if document.encrypted:
                from adaptive_document_agent.extraction.pdf_parser import PDFValidationError
                raise PDFValidationError("The PDF is encrypted. Upload an unlocked PDF.")
            if self.cache:
                self.cache.set_model(f"document-v4-{digest}", document)
        if document.encrypted:
            from adaptive_document_agent.extraction.pdf_parser import PDFValidationError
            raise PDFValidationError("The PDF is encrypted. Upload an unlocked PDF.")
        return document

    @staticmethod
    def _merge_observations(existing: list[Observation], targeted: list[Observation]) -> list[Observation]:
        """Preserve the broad fact base and add only genuinely new targeted facts."""
        merged = {item.id: item for item in existing}
        for item in targeted:
            merged.setdefault(item.id, item)
        return list(merged.values())

    @staticmethod
    def _reconstruct_tables(document: ParsedDocument) -> None:
        reconstructor = TableReconstructor()
        all_tables = [table for page in document.pages for table in page.tables]
        combined = reconstructor.combine_continuations(all_tables)
        by_page: dict[int, list[object]] = {}
        for table in combined:
            by_page.setdefault(table.page, []).append(table)
        for page in document.pages:
            page.tables = by_page.get(page.page_number, [])  # type: ignore[assignment]

    @staticmethod
    def _diagnose_zero_charts(
        document: ParsedDocument,
        observations: list[Observation],
        index: object,
    ) -> tuple[str, dict[str, list[str]]]:
        from adaptive_document_agent.document_model.chartability import score_chartability
        from adaptive_document_agent.document_model.series import (
            best_period_series,
            conflicting_groups,
            is_meaningful_metric,
        )

        tables_detected = sum(len(p.tables) for p in document.pages)
        observations_extracted = len(observations)
        observations_retained = len(getattr(index, "observations", []))
        metrics_found = sorted(index.metrics()) if hasattr(index, "metrics") else []

        failure_reasons: dict[str, list[str]] = {}
        for metric in metrics_found:
            m_obs = index.for_metric(metric) if hasattr(index, "for_metric") else []
            if not m_obs:
                failure_reasons[metric] = ["No observations found in index for metric"]
                continue
            if not is_meaningful_metric(m_obs[0]):
                failure_reasons[metric] = ["Failed is_meaningful_metric check (generic/non-metric label)"]
                continue
            if conflicting_groups(m_obs):
                failure_reasons[metric] = ["Conflicting observation groups detected for metric"]
                continue
            series = best_period_series(m_obs)
            if len(series) < 2:
                periods_found = [o.period for o in m_obs if o.period]
                failure_reasons[metric] = [
                    f"Fewer than 2 distinct periods in best series (periods found: {periods_found})"
                ]
                continue
            if any(not item.evidence for item in series):
                failure_reasons[metric] = ["Series observations missing source evidence"]
                continue
            res = score_chartability(series)
            if not res.is_chartable:
                failure_reasons[metric] = res.reasons or [
                    f"score_chartability returned is_chartable=False (score={res.score:.2f})"
                ]

        lines = [
            "[DIAGNOSTIC: charts == 0]",
            f"Tables detected across document: {tables_detected}",
            f"Observations extracted: {observations_extracted}",
            f"Observations retained in model index: {observations_retained}",
            f"Metrics found ({len(metrics_found)}): {', '.join(metrics_found) if metrics_found else 'None'}",
        ]
        if failure_reasons:
            lines.append("Chartability failure reasons by candidate metric:")
            for m, reasons in sorted(failure_reasons.items()):
                lines.append(f"  - '{m}': {'; '.join(reasons)}")
        else:
            lines.append("No candidate metrics evaluated for chartability.")

        return "\n".join(lines), failure_reasons


def analyse_pdf(
    file: bytes | bytearray | BinaryIO,
    settings: object | None = None,
    *,
    gateway: LLMGateway | None = None,
    progress: ProgressCallback | None = None,
    analysis_focus: str | None = None,
    scope: AnalysisScopePreview | None = None,
    presentation_budget: PresentationBudget | None = None,
) -> PipelineResult:
    """Stable orchestration API used by the Streamlit shell and future adapters."""
    return DocumentOrchestrator(gateway).analyse_pdf(file, settings, progress=progress,
        analysis_focus=analysis_focus, scope=scope, presentation_budget=presentation_budget)
