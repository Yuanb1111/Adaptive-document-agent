"""Public domain models used across pipeline stages."""

from .analysis import AnalysisCandidate, AnalysisResult, AnalysisTask, CandidateScore
from .chart import ChartPlan, ChartType
from .document import AnalysisPageRange, AnalysisScopePreview, DocumentProfile, ParsedDocument
from .evidence import SourceEvidence
from .fact import CanonicalFact
from .observation import FinancialObservation, Observation
from .page import DocumentPage, PageImage
from .presentation import (
    CompanyFact,
    CompanyProfile,
    PresentationBlockRole,
    PresentationLayout,
    PresentationPlan,
    PresentationSlide,
    PresentationSlideRole,
    PresentationSlideType,
    PresentationVisualBlock,
)
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
    "CanonicalFact",
    "ChartPlan",
    "ChartType",
    "CompanyFact",
    "CompanyProfile",
    "DocumentPage",
    "DocumentProfile",
    "ExtractedTable",
    "FinancialObservation",
    "Insight",
    "Observation",
    "PageImage",
    "ParsedDocument",
    "PipelineResult",
    "PresentationPlan",
    "PresentationBlockRole",
    "PresentationLayout",
    "PresentationSlide",
    "PresentationSlideRole",
    "PresentationSlideType",
    "PresentationVisualBlock",
    "ReportPlan",
    "ReportSection",
    "SourceEvidence",
    "TableRow",
    "ValidationIssue",
    "ValidationReport",
]
