"""Final report checks for unsupported numeric claims."""

import re

from adaptive_document_agent.models import AnalysisResult, ValidationIssue, ValidationReport


class ReportValidator:
    def validate(self, markdown: str, results: list[AnalysisResult]) -> ValidationReport:
        report = ValidationReport()
        if re.search(r"(?i)\b(caused|proves|guarantees)\b", markdown):
            report.add(ValidationIssue(code="causal_language", message="Report contains potentially unsupported causal language.", stage="report"))
        if any(result.result is not None and not result.evidence for result in results):
            report.add(ValidationIssue(code="unsupported_result", message="At least one report result lacks evidence.", severity="error", stage="report"))
        return report

