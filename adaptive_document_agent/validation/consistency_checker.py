"""Generic total-versus-components consistency checks."""

from collections import defaultdict

from adaptive_document_agent.models import Observation, ValidationIssue, ValidationReport


class ConsistencyChecker:
    def __init__(self, *, relative_tolerance: float = 0.02) -> None:
        self.relative_tolerance = relative_tolerance

    def validate(self, observations: list[Observation]) -> ValidationReport:
        report = ValidationReport()
        groups: dict[tuple[str | None, str | None, str | None], list[Observation]] = defaultdict(list)
        for item in observations:
            groups[(item.metric_canonical or item.metric_original, item.period, item.entity)].append(item)
        for (metric, period, _), items in groups.items():
            totals = [item for item in items if any(value.casefold() in {"total", "all"} for value in item.dimensions.values())]
            components = [item for item in items if item not in totals and item.dimensions and item.value is not None]
            for total in totals:
                if total.value is None or not components:
                    continue
                component_sum = sum(float(item.value) for item in components)
                denominator = max(abs(total.value), 1.0)
                if abs(component_sum - total.value) / denominator > self.relative_tolerance:
                    report.add(ValidationIssue(code="total_mismatch", message=f"Reported total for {metric} ({period or 'unknown period'}) does not match extracted components.", stage="consistency", related_ids=[total.id, *[item.id for item in components]], evidence=total.evidence))
        return report

