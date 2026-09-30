"""Serializable findings from the native PowerPoint preflight gate."""

from dataclasses import dataclass, field

from .ppt_preflight import PreflightIssue
from .qa_reporter import CriticalQAError


@dataclass
class PreflightReport:
    issues: list[PreflightIssue] = field(default_factory=list)
    completed: bool = False

    @property
    def errors(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def status(self) -> str:
        if self.errors:
            return "failed"
        if not self.completed and not self.issues:
            return "not_run"
        return "passed_with_warnings" if any(i.severity == "warning" for i in self.issues) else "passed"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "is_export_blocked": bool(self.errors),
            "issues": [
                {"slide": issue.slide_idx + 1, "code": issue.code,
                 "severity": issue.severity, "message": issue.message}
                for issue in self.issues
            ],
        }


class PreflightQAError(CriticalQAError):
    """Error-level native findings block export even if sanitization ran."""

    def __init__(self, report: PreflightReport):
        detail = "; ".join(str(issue) for issue in report.errors[:8])
        super().__init__("PowerPoint preflight export gate blocked: " + detail, preflight_report=report)
