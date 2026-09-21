"""One downloadable report for financial, build and rendered export failures."""

from .qa_reporter import run_comprehensive_qa


def export_diagnostics(result, error=None, visual_report=None) -> dict:
    # Do not run another repair pass while reporting an earlier failure: that
    # can produce a misleading 'passed' report for a blocked export attempt.
    financial = getattr(error, "financial_report", None) or run_comprehensive_qa(result.model_copy(deep=True), auto_repair=False)
    report = financial.model_dump()
    report["financial_qa"] = financial.model_dump()
    report["visual_qa"] = visual_report.to_dict() if visual_report else None
    report["export_error"] = None
    if visual_report:
        for issue in visual_report.issues:
            if issue.severity == "critical":
                report["critical_errors"].append({"code": issue.code, "severity": "CRITICAL",
                    "message": issue.message, "slide_id": str(issue.slide) if issue.slide else None,
                    "related_ids": list(issue.shape_ids)})
    if error:
        stage = "rendering" if visual_report else "financial" if financial.has_critical_errors else "generation"
        report["export_error"] = {"stage": stage, "message": str(error)}
        if not report["critical_errors"]:
            report["critical_errors"].append({"code": "EXPORT_FAILED", "severity": "CRITICAL",
                "message": str(error), "slide_id": None, "related_ids": []})
    report["is_export_blocked"] = bool(error or report["critical_errors"] or (visual_report and visual_report.status == "failed"))
    return report
