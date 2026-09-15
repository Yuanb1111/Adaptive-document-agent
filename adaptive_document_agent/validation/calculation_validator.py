"""Validate calculation outputs and evidence inputs."""

import math

from adaptive_document_agent.models import AnalysisResult, ValidationIssue, ValidationReport


class CalculationValidator:
    def validate(self, results: list[AnalysisResult]) -> ValidationReport:
        report = ValidationReport()
        for result in results:
            if result.result is None:
                report.add(ValidationIssue(code="calculation_failed", message=f"Calculation failed: {result.title}.", severity="error", stage="calculation", related_ids=[result.task_id]))
            if isinstance(result.result, float) and not math.isfinite(result.result):
                report.add(ValidationIssue(code="non_finite", message=f"Non-finite result: {result.title}.", severity="error", stage="calculation", related_ids=[result.task_id]))
            for warning in result.warnings:
                report.add(ValidationIssue(code="calculation_warning", message=warning, stage="calculation", related_ids=[result.task_id]))
        return report

