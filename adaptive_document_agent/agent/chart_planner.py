"""Plan traceable charts from calculations and validated reported series."""

import re

from adaptive_document_agent.document_model import DocumentIndex, best_period_series, conflicting_groups, metric_key, paired_observations, period_sort_key
from adaptive_document_agent.models import AnalysisResult, AnalysisTask, ChartPlan, ChartType, Observation
from adaptive_document_agent.utils.ids import stable_id


class ChartPlanner:
    _MAPPING = {
        "linear_trend": "line",
        "compare_periods": "line",
        "percentage_change": "line",
        "absolute_change": "line",
        "rank_values": "bar",
        "compare_categories": "bar",
        "contribution_share": "pie",
        "pearson_correlation": "scatter",
        "spearman_correlation": "scatter",
    }

    def plan(
        self,
        tasks: list[AnalysisTask],
        results: list[AnalysisResult],
        index: DocumentIndex,
        *,
        preferred_metrics: list[str] | None = None,
        maximum: int = 10,
    ) -> list[ChartPlan]:
        valid_tasks = {result.task_id for result in results if result.result is not None and result.evidence}
        output: list[ChartPlan] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        seen_metrics: set[str] = set()
        for task in tasks:
            chart_type = self._MAPPING.get(task.analysis_type)
            identifiers = list(task.observation_query.get("observation_ids", []))
            observations = [index.get(identifier) for identifier in identifiers]
            observations = [item for item in observations if item and item.value is not None]
            if not chart_type or task.id not in valid_tasks or len(observations) < 2:
                continue
            x_metric = task.required_metrics[0] if task.required_metrics else None
            y_metric = task.required_metrics[1] if len(task.required_metrics) > 1 else x_metric
            if chart_type == "scatter":
                if not x_metric or not y_metric:
                    continue
                pairs = paired_observations(observations, x_metric, y_metric)
                if len(pairs) < 5:
                    continue
                observations = [item for pair in pairs for item in pair]
                identifiers = [item.id for item in observations]
            else:
                observations = sorted(observations, key=lambda item: period_sort_key(item.period))
                identifiers = [item.id for item in observations]
            key = chart_type, tuple(sorted(identifiers))
            if key in seen:
                continue
            seen.add(key)
            seen_metrics.update(metric_key(item) for item in observations)
            pages = sorted({source.page for identifier in identifiers if (item := index.get(identifier)) for source in item.evidence})
            output.append(
                ChartPlan(
                    id=stable_id("chart", task.id),
                    title=task.title,
                    chart_type=chart_type,
                    question=task.reason,
                    observation_ids=identifiers,
                    source_pages=pages,
                    analysis_task_id=task.id,
                    available_chart_types=self._available_types(task, observations),
                    x_metric=x_metric,
                    y_metric=y_metric,
                    x_dimension=task.required_dimensions[0] if task.required_dimensions else None,
                    x_axis_title=self._x_title(task, observations),
                    y_axis_title=self._metric_title(y_metric or x_metric, observations),
                )
            )
            if len(output) >= maximum:
                break
        if len(output) < maximum:
            output.extend(
                self._reported_series_charts(
                    index,
                    seen_metrics=seen_metrics,
                    preferred_metrics=preferred_metrics or [],
                    maximum=maximum - len(output),
                )
            )
        return output

    def _reported_series_charts(
        self,
        index: DocumentIndex,
        *,
        seen_metrics: set[str],
        preferred_metrics: list[str],
        maximum: int,
    ) -> list[ChartPlan]:
        """Visualise safe reported series even when no calculation was selected."""
        preferred = [name.casefold().strip() for name in preferred_metrics if name.strip()]
        candidates: list[tuple[tuple[float, ...], str, list[Observation]]] = []
        for metric in index.metrics():
            if metric in seen_metrics or metric in {"page", "pages"}:
                continue
            observations = index.for_metric(metric)
            if conflicting_groups(observations):
                continue
            series = best_period_series(observations)
            if len(series) < 2 or any(not item.evidence for item in series):
                continue
            relevance = 1.0 if any(name in metric or metric in name for name in preferred) else 0.0
            confidence = sum(item.confidence for item in series) / len(series)
            distinct_pages = len({source.page for item in series for source in item.evidence})
            candidates.append(((relevance, float(len(series)), confidence, float(distinct_pages)), metric, series))

        output: list[ChartPlan] = []
        for _, metric, series in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[:maximum]:
            identifiers = [item.id for item in series]
            pages = sorted({source.page for item in series for source in item.evidence})
            label = series[0].metric_canonical or series[0].metric_original
            table_context = series[0].dimensions.get("table_context")
            title = f"{table_context} — {label}" if self._displayable_context(table_context, label) else label
            default_type: ChartType = "line" if len(series) >= 4 else "bar"
            output.append(
                ChartPlan(
                    id=stable_id("chart", "reported_series", metric, *identifiers),
                    title=f"{title} — Reported Values",
                    chart_type=default_type,
                    question="How do the directly reported values compare across compatible periods?",
                    observation_ids=identifiers,
                    source_pages=pages,
                    available_chart_types=["line", "bar", "area", "table"],
                    x_metric=metric,
                    y_metric=metric,
                    x_axis_title="Period",
                    y_axis_title=self._metric_title(label, series),
                )
            )
        return output

    @staticmethod
    def _displayable_context(context: str | None, label: str) -> bool:
        if not context or context.casefold() in label.casefold():
            return False
        lowered = context.casefold()
        if len(context) > 80 or re.search(r"(?:\.\s*){3,}|\d{1,3},\d{3}", context):
            return False
        if re.search(r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", lowered):
            return False
        return context.isupper() or context.istitle()

    @staticmethod
    def _available_types(task: AnalysisTask, observations: list[Observation]) -> list[ChartType]:
        if task.analysis_type in {"pearson_correlation", "spearman_correlation"}:
            return ["scatter", "table"]
        if task.analysis_type in {"rank_values", "compare_categories"}:
            return ["bar", "horizontal_bar", "table"]
        if task.analysis_type == "contribution_share":
            values = [float(item.value) for item in observations if item.value is not None]
            choices: list[ChartType] = ["bar", "horizontal_bar", "table"]
            if 2 <= len(values) <= 8 and all(value >= 0 for value in values):
                choices.insert(0, "pie")
            return choices
        return ["line", "bar", "area", "table"]

    @staticmethod
    def _x_title(task: AnalysisTask, observations: list[Observation]) -> str:
        if task.analysis_type in {"pearson_correlation", "spearman_correlation"}:
            return task.required_metrics[0].title() if task.required_metrics else "First metric"
        if task.required_dimensions:
            return task.required_dimensions[0].replace("_", " ").title()
        if any(item.period for item in observations):
            return "Period"
        return "Category"

    @staticmethod
    def _metric_title(metric: str | None, observations: list[Observation]) -> str:
        name = (metric or "Value").replace("_", " ").title()
        currencies = sorted({item.currency for item in observations if item.currency})
        units = sorted({item.unit for item in observations if item.unit and item.unit != "currency"})
        suffix = " / ".join([*currencies, *units])
        return f"{name} ({suffix})" if suffix else name
