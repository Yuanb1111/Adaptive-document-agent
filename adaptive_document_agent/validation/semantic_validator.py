"""Detect risky semantic merges."""

from collections import defaultdict
import re

from adaptive_document_agent.models import Observation, ValidationIssue, ValidationReport


class SemanticValidator:
    def validate(self, observations: list[Observation]) -> ValidationReport:
        report = ValidationReport()
        mapped: dict[str, set[str]] = defaultdict(set)
        qualifiers = {"gross", "net", "total", "segment", "adjusted"}
        for item in observations:
            if item.metric_canonical:
                mapped[" ".join(item.metric_canonical.casefold().split())].add(" ".join(item.metric_original.casefold().split()))
        for canonical, originals in mapped.items():
            signatures = {frozenset(qualifiers.intersection(re.findall(r"\b\w+\b", name)))
                          for name in originals}
            if len(originals) > 1 and len(signatures) > 1:
                report.add(ValidationIssue(code="possible_over_normalization", message=f"Canonical metric '{canonical}' merges differently qualified originals: {sorted(originals)}.", stage="semantic"))
        return report

