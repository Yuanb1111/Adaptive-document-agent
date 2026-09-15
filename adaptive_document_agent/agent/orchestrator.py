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
            cached_tables = self.cache.get_model(f"tables-v5-{digest}-{scope}", ParsedDocument) if self.cache else None
            if cached_tables is not None:
                document = cached_tables
            else:
                tables_by_page = TableExtractor().extract(raw, page_numbers=page_numbers)
                for page in document.pages:
                    page.tables = tables_by_page.get(page.page_number, [])
                self._reconstruct_tables(document)
                if self.cache:
                    self.cache.set_model(f"tables-v5-{digest}-{scope}", document)

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
            charts = ChartPlanner().plan(plan, results, index, preferred_metrics=profile.metrics)
            markdown = ReportGenerator().generate(
                profile,
                report_plan,
                insights,
                issues,
                observations=index.observations,
                charts=charts,
            )
            issues.extend(ReportValidator().validate(markdown, results).issues)

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
