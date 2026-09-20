"""Validated task execution through deterministic tools."""

from math import isfinite

from adaptive_document_agent.document_model import (
    DocumentIndex,
    are_periods_comparable,
    conflicting_groups,
    paired_observations,
    reconcile_observations,
)
from adaptive_document_agent.extraction.normalizer import UnitSignature, compatible_units
from adaptive_document_agent.models import AnalysisResult, AnalysisTask, Observation
from adaptive_document_agent.tools import ToolRegistry, create_default_registry
from adaptive_document_agent.tools.safe_formula import evaluate_formula


class AnalysisExecutor:
    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or create_default_registry()

    def execute(self, tasks: list[AnalysisTask], index: DocumentIndex) -> list[AnalysisResult]:
        return [self._execute_one(task, index) for task in tasks]

    def _execute_one(self, task: AnalysisTask, index: DocumentIndex) -> AnalysisResult:
        observations = [index.get(identifier) for identifier in task.observation_query.get("observation_ids", [])]
        valid = [item for item in observations if item is not None and item.value is not None]
        warnings: list[str] = []
        try:
            valid, reconciled = reconcile_observations(valid)
            if reconciled:
                warnings.append("Presentation-sign variants were separated; the calculation used one coherent source series.")
            conflicts = conflicting_groups(valid)
            if conflicts:
                raise ValueError("Calculation blocked because same-context source values conflict.")
            self._validate_units(valid, task.analysis_type)
            self._validate_periods(valid, task.analysis_type)
            if task.formula:
                variables = {self._variable_name(item): float(item.value) for item in valid}
                value = evaluate_formula(task.formula, variables)
            else:
                value = self._dispatch(task, valid)
            if isinstance(value, float) and not isfinite(value):
                raise ValueError("Calculation returned a non-finite result.")
            confidence = min((item.confidence for item in valid), default=0.0)
        except (ValueError, KeyError) as exc:
            value, confidence = None, 0.0
            warnings.append(str(exc))
        evidence = []
        for item in valid:
            evidence.extend(source for source in item.evidence if source not in evidence)
        return AnalysisResult(
            task_id=task.id,
            title=task.title,
            result_type="calculated_result",
            result=value,
            input_observation_ids=[item.id for item in valid],
            warnings=warnings,
            evidence=evidence,
            confidence=confidence,
        )

    def _dispatch(self, task: AnalysisTask, observations: list[Observation]) -> object:
        name = task.tool_name or task.analysis_type
        if name in {"absolute_change", "percentage_change", "growth_rate", "cagr", "linear_trend", "moving_average", "compare_periods"}:
            ordered = sorted(observations, key=lambda item: item.period or "")
        else:
            ordered = observations
        from adaptive_document_agent.validation.claim_validator import is_expense_metric

        values = [float(item.value) for item in ordered if item.value is not None]
        is_exp = any(
            is_expense_metric(getattr(item, "metric_canonical", "") or getattr(item, "metric_original", ""))
            for item in ordered
        )
        if name in {"absolute_change", "percentage_change", "growth_rate"}:
            if name in {"percentage_change", "growth_rate"} and is_exp:
                return self.registry.execute(name, start=values[0], end=values[-1], is_expense=True)
            return self.registry.execute(name, start=values[0], end=values[-1])
        if name == "cagr":
            if is_exp:
                return self.registry.execute(name, start=values[0], end=values[-1], periods=len(values) - 1, is_expense=True)
            return self.registry.execute(name, start=values[0], end=values[-1], periods=len(values) - 1)
        if name in {"rank_values", "top_n", "bottom_n", "compare_categories"}:
            labels = [next(iter(item.dimensions.values()), item.entity or item.period or item.id) for item in ordered]
            return self.registry.execute(name, labels=labels, values=values)
        if name == "compare_periods":
            return self.registry.execute(name, labels=[item.period or item.id for item in ordered], values=values)
        if name in {"pearson_correlation", "spearman_correlation"}:
            pairs = self._paired_series(task, observations)
            return self.registry.execute(name, left=pairs[0], right=pairs[1])
        return self.registry.execute(name, values=values)

    @staticmethod
    def _paired_series(task: AnalysisTask, observations: list[Observation]) -> tuple[list[float], list[float]]:
        names = [name.casefold() for name in task.required_metrics]
        if len(names) != 2:
            raise ValueError("Correlation requires two metrics.")
        pairs = paired_observations(observations, names[0], names[1])
        if len(pairs) < 5:
            raise ValueError("Correlation requires at least five conflict-free paired observations.")
        return (
            [float(left.value) for left, _ in pairs if left.value is not None],
            [float(right.value) for _, right in pairs if right.value is not None],
        )

    @staticmethod
    def _validate_units(observations: list[Observation], analysis_type: str) -> None:
        if analysis_type in {"pearson_correlation", "spearman_correlation", "ratio"}:
            return
        signatures = {UnitSignature(item.unit, item.currency) for item in observations}
        if len(signatures) > 1:
            first = next(iter(signatures))
            if not all(compatible_units(first, other) for other in signatures):
                raise ValueError("Analysis inputs have incompatible units or currencies.")

    @staticmethod
    def _validate_periods(observations: list[Observation], analysis_type: str) -> None:
        """Block flow/trend calculations across incompatible reporting durations."""
        period_analyses = {
            "absolute_change", "percentage_change", "growth_rate", "cagr",
            "linear_trend", "moving_average", "compare_periods",
        }
        if analysis_type not in period_analyses:
            return
        periods = [item.period for item in observations if item.period]
        for index, left in enumerate(periods):
            for right in periods[index + 1:]:
                comparable, reason = are_periods_comparable(left, right)
                if not comparable:
                    raise ValueError(f"Analysis inputs have incompatible periods: {reason}")

    @staticmethod
    def _variable_name(observation: Observation) -> str:
        return "".join(character if character.isalnum() else "_" for character in (observation.metric_canonical or observation.metric_original).casefold()).strip("_")
