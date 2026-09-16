"""Public domain models used across pipeline stages."""

from .analysis import AnalysisCandidate, AnalysisResult, AnalysisTask, CandidateScore
from .chart import ChartPlan, ChartType
from .document import AnalysisPageRange, AnalysisScopePreview, DocumentProfile, ParsedDocument
from .evidence import SourceEvidence
from .observation import Observation
from .page import DocumentPage, PageImage
from .presentation import CompanyFact, CompanyProfile, PresentationPlan, PresentationSlide, PresentationSlideType
from .report import Insight, PipelineResult, ReportPlan, ReportSection
from .table import ExtractedTable, TableRow
from .validation import ValidationIssue, ValidationReport

__all__ = [
    "AnalysisCandidate",
    "AnalysisPageRange",
    "AnalysisResult",
    "AnalysisScopePreview",
    "AnalysisTask",
    "CandidateScore",
    "ChartPlan",
    "ChartType",
    "CompanyFact",
    "CompanyProfile",
    "DocumentPage",
    "DocumentProfile",
    "ExtractedTable",
    "Insight",
    "Observation",
    "PageImage",
    "ParsedDocument",
    "PipelineResult",
    "PresentationPlan",
    "PresentationSlide",
    "PresentationSlideType",
    "ReportPlan",
    "ReportSection",
    "SourceEvidence",
    "TableRow",
    "ValidationIssue",
    "ValidationReport",
]
