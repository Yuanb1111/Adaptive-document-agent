"""Require page evidence for important numeric results."""

from adaptive_document_agent.models import AnalysisResult, ValidationIssue, ValidationReport


class EvidenceValidator:
    def validate(self, results: list[AnalysisResult]) -> ValidationReport:
        report = ValidationReport()
        for result in results:
            if result.result is not None and not result.evidence:
                report.add(ValidationIssue(code="missing_evidence", message=f"Result has no source evidence: {result.title}.", severity="error", stage="evidence", related_ids=[result.task_id]))
        return report

