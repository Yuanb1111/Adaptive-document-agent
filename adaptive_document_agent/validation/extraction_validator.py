"""Observation-level extraction quality checks."""

from adaptive_document_agent.models import Observation, ValidationIssue, ValidationReport
from adaptive_document_agent.document_model import conflicting_groups, presentation_sign_variant_groups


class ExtractionValidator:
    def validate(self, observations: list[Observation]) -> ValidationReport:
        report = ValidationReport()
        seen: dict[tuple[object, ...], Observation] = {}
        low_confidence: dict[str, list[Observation]] = {}
        for item in observations:
            if item.value is None:
                report.add(ValidationIssue(code="missing_value", message=f"{item.metric_original} has no numeric value.", stage="extraction", related_ids=[item.id]))
            if item.confidence < 0.5:
                low_confidence.setdefault(item.metric_original, []).append(item)
            key = (item.metric_original.casefold(), item.period, item.entity, tuple(sorted(item.dimensions.items())))
            seen.setdefault(key, item)
        for metric, items in low_confidence.items():
            report.add(ValidationIssue(code="low_confidence", message=f"{len(items)} low-confidence observation(s) for {metric}.", stage="extraction", related_ids=[item.id for item in items], evidence=[source for item in items[:3] for source in item.evidence]))
        for items in presentation_sign_variant_groups(observations):
            report.add(ValidationIssue(code="presentation_sign_variance", message=f"Presentation signs differ for {items[0].metric_original}; raw values were retained and source series kept separate.", stage="extraction", severity="warning", related_ids=[item.id for item in items], evidence=[source for item in items[:3] for source in item.evidence]))
        for items in conflicting_groups(observations):
            report.add(ValidationIssue(code="conflicting_values", message=f"Conflicting values for {items[0].metric_original} ({len(items)} observations).", stage="extraction", severity="error", related_ids=[item.id for item in items], evidence=[source for item in items[:3] for source in item.evidence]))
        return report
