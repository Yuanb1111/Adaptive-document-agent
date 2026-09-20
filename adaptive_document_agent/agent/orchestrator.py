"""End-to-end pipeline; UI and providers depend on this stable API."""

from collections.abc import Callable
from typing import BinaryIO

from adaptive_document_agent.document_model import DocumentModelBuilder
from adaptive_document_agent.extraction.chart_extractor import ChartExtractor
from adaptive_document_agent.extraction.observation_extractor import ObservationExtractor
from adaptive_document_agent.extraction.pdf_parser import PDFParser
from adaptive_document_agent.extraction.table_extractor import TableExtractor
from adaptive_document_agent.extraction.table_reconstructor import TableReconstructor
from adaptive_document_agent.extraction.vision_adapter import VisionAdapter
from adaptive_document_agent.models import AnalysisScopePreview, Observation, ParsedDocument, PipelineResult, ValidationIssue
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.timing import record_timing
from adaptive_document_agent.validation import CalculationValidator, ConsistencyChecker, CoverageValidator, EvidenceValidator, ExtractionValidator, SemanticValidator
from adaptive_document_agent.validation.report_validator import ReportValidator

from .analysis_planner import AnalysisPlanner
from .candidate_generator import AnalysisCandidateGenerator
from .chart_planner import ChartPlanner
from .document_discovery import DocumentDiscovery
from .executor import AnalysisExecutor
from .insight_generator import InsightGenerator
from .presentation_planner import PresentationPlanner
from .presentation_plan_recovery import PresentationPlanRecovery
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

    def analyse_pdf(
        self,
        file: bytes | bytearray | BinaryIO,
        settings: object | None = None,
        *,
        progress: ProgressCallback | None = None,
        analysis_focus: str | None = None,
        scope: AnalysisScopePreview | None = None,
    ) -> PipelineResult:
        del settings  # Configuration is enforced when constructing the gateway.
        notify = progress or (lambda _: None)
        timings: dict[str, int] = {}
        raw = bytes(file) if isinstance(file, (bytes, bytearray)) else file.read()
        digest = sha256_bytes(raw)

        notify("Reading PDF")
        with record_timing(timings, "pdf_ingestion"):
            document = self._load_document(raw, digest)
        if scope and (scope.document_sha256 != digest or scope.page_count != document.page_count):
            raise ValueError("The confirmed analysis scope does not belong to this PDF.")

        notify("Understanding document")
        with record_timing(timings, "document_discovery"):
            profile = DocumentDiscovery(self.gateway).discover(
                document,
                analysis_focus=analysis_focus,
                progress=notify,
                routed_ranges=scope.page_ranges if scope else None,
            )

        notify("Extracting tables from selected sections")
        with record_timing(timings, "table_extraction"):
            page_numbers = (
                {page for start, end in profile.analysis_page_ranges for page in range(start, end + 1)}
                if profile.analysis_page_ranges
                else None
            )
            scope = sha256_bytes(str(profile.analysis_page_ranges or "all").encode("utf-8"))[:16]
            cached_tables = self.cache.get_model(f"tables-v6-{digest}-{scope}", ParsedDocument) if self.cache else None
            if cached_tables is not None:
                document = cached_tables
            else:
                tables_by_page = TableExtractor().extract(raw, page_numbers=page_numbers)
                for page in document.pages:
                    page.tables = tables_by_page.get(page.page_number, [])
                self._reconstruct_tables(document)
                if self.cache:
                    self.cache.set_model(f"tables-v6-{digest}-{scope}", document)

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

            observations = FinancialNormalizer.normalize_observations(
                observations,
                default_currency=getattr(profile, "currency", "RMB") or "RMB",
            )

        notify("Building document model")
        with record_timing(timings, "document_model"):
            index = DocumentModelBuilder().build(observations)

        notify("Generating analysis candidates")
        with record_timing(timings, "candidate_generation"):
            candidates = AnalysisCandidateGenerator(self.gateway).generate(index, profile)
            scores = AnalysisValueScorer(self.gateway).score(candidates, index, profile)

        notify("Selecting useful analyses")
        with record_timing(timings, "analysis_planning"):
            plan = AnalysisPlanner().plan(scores, index)

        notify("Extracting required data")
        with record_timing(timings, "targeted_extraction"):
            required_metrics = {metric for task in plan for metric in task.required_metrics}
            targeted = extractor.extract(document, required_metrics=required_metrics, page_ranges=profile.analysis_page_ranges) if required_metrics else []
            if targeted:
                for observation in targeted:
                    mapping = mapping_by_name.get(observation.metric_original)
                    if mapping and mapping.confidence >= 0.7:
                        observation.metric_canonical = mapping.canonical_name
                observations = self._merge_observations(observations, targeted)
                observations = FinancialNormalizer.normalize_observations(
                    observations,
                    default_currency=getattr(profile, "currency", "RMB") or "RMB",
                )
                index = DocumentModelBuilder().build(observations)

        notify("Running deterministic calculations")
        with record_timing(timings, "execution"):
            results = AnalysisExecutor().execute(plan, index)

        notify("Checking consistency and validating results")
        with record_timing(timings, "validation"):
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

        selected_pages = [
            page
            for page in document.pages
            if not profile.analysis_page_ranges or any(start <= page.page_number <= end for start, end in profile.analysis_page_ranges)
        ]
        candidates_images = ChartExtractor().candidates(selected_pages)
        if candidates_images and self.gateway:
            vision_warning = VisionAdapter(self.gateway).unavailable_message()
            if vision_warning:
                profile.data_quality_notes.append(vision_warning)
        elif candidates_images:
            profile.data_quality_notes.append("Chart candidates were detected; no vision model is configured.")

        notify("Generating insights and dynamic report")
        with record_timing(timings, "reporting"):
            insights = InsightGenerator(self.gateway).generate(results)
            report_plan = DynamicReportPlanner(self.gateway).plan(profile, insights)
            charts = ChartPlanner().plan(
                plan,
                results,
                index,
                preferred_metrics=profile.metrics,
                insights=insights,
                report_plan=report_plan,
                analysis_focus=analysis_focus,
            )
            markdown = ReportGenerator().generate(
                profile,
                report_plan,
                insights,
                issues,
                observations=index.observations,
                charts=charts,
            )
            issues.extend(ReportValidator().validate(markdown, results).issues)

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
                for p in document.pages:
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

                # 2. Re-extract observations across full document (includes deterministic vertical text fallback)
                recovered = extractor.extract(document, page_ranges=profile.analysis_page_ranges or None)
                if recovered:
                    recovered = FinancialNormalizer.normalize_observations(
                        recovered,
                        default_currency=getattr(profile, "currency", "RMB") or "RMB",
                    )
                    observations = self._merge_observations(observations, recovered)
                    index = DocumentModelBuilder().build(observations)

                    # 3. Regenerate candidate analyses and results if plan lacked depth or charts == 0
                    if len(results) < 2 or not plan or not charts:
                        candidates = AnalysisCandidateGenerator(self.gateway).generate(index, profile)
                        scores = AnalysisValueScorer(self.gateway).score(candidates, index, profile)
                        plan = AnalysisPlanner().plan(scores, index)
                        results = AnalysisExecutor().execute(plan, index)

                    charts = ChartPlanner().plan(
                        plan,
                        results,
                        index,
                        preferred_metrics=profile.metrics,
                        insights=insights,
                        report_plan=report_plan,
                        analysis_focus=analysis_focus,
                    )
                    if charts and report_plan:
                        markdown = ReportGenerator().generate(
                            profile,
                            report_plan,
                            insights,
                            issues,
                            observations=index.observations,
                            charts=charts,
                        )

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
                    validation_warnings=issues,
                )
                try:
                    presentation_plan = PresentationPlanner(self.gateway).plan(planning_result)
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
                        presentation_plan = PresentationPlanRecovery().fallback(planning_result)
                        issues.append(
                            ValidationIssue(
                                code="presentation_plan_fallback",
                                message="An evidence-only presentation plan was generated in place of the invalid AI plan.",
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
                    from adaptive_document_agent.validation.claim_validator import repair_presentation_plan
                    from adaptive_document_agent.validation.cross_slide_validator import CrossSlideValidator

                    presentation_plan, plan_repairs = repair_presentation_plan(presentation_plan, index.observations)
                    for repair_msg in plan_repairs:
                        issues.append(
                            ValidationIssue(
                                code="claim_contradiction_repaired",
                                message=repair_msg,
                                severity="info",
                                stage="presentation",
                            )
                        )
                    cross_val = CrossSlideValidator(presentation_plan, index.observations)
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

        notify("Complete")
        return PipelineResult(
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
            validation_warnings=issues,
            llm_usage=list(self.gateway.usage) if self.gateway else [],
            timings_ms=timings,
        )

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
        document = self.cache.get_model(f"document-v1-{digest}", ParsedDocument) if self.cache else None
        if document is None:
            document = PDFParser().parse(raw, extract_tables=False)
            if self.cache:
                self.cache.set_model(f"document-v1-{digest}", document)
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
) -> PipelineResult:
    """Stable orchestration API used by the Streamlit shell and future adapters."""
    return DocumentOrchestrator(gateway).analyse_pdf(file, settings, progress=progress, analysis_focus=analysis_focus, scope=scope)
