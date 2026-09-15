"""Detect risky semantic merges."""

from collections import defaultdict

from adaptive_document_agent.models import Observation, ValidationIssue, ValidationReport


class SemanticValidator:
    def validate(self, observations: list[Observation]) -> ValidationReport:
        report = ValidationReport()
        mapped: dict[str, set[str]] = defaultdict(set)
        qualifiers = {"gross", "net", "total", "segment", "adjusted"}
        for item in observations:
            if item.metric_canonical:
                mapped[item.metric_canonical.casefold()].add(item.metric_original.casefold())
        for canonical, originals in mapped.items():
            present = {word for name in originals for word in qualifiers if word in name.split()}
            if len(present) > 1:
                report.add(ValidationIssue(code="possible_over_normalization", message=f"Canonical metric '{canonical}' merges differently qualified originals: {sorted(originals)}.", stage="semantic"))
        return report

