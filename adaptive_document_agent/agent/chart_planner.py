"""Plan traceable charts from calculations and validated reported series."""

from collections import Counter
import re

from adaptive_document_agent.document_model import (
    DocumentIndex,
    best_period_series,
    conflicting_groups,
    display_metric_name,
    is_meaningful_metric,
    metric_key,
    paired_observations,
    period_sort_key,
)
from adaptive_document_agent.models import (
    AnalysisResult,
    AnalysisTask,
    ChartPlan,
    ChartType,
    Insight,
    Observation,
    ReportPlan,
)
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

    _PERIPHERAL_TERMS = (
        "prepaid",
        "advance payment",
        "deposit",
        "other payable",
        "other receivable",
        "miscellaneous",
        "petty",
        "stamp duty",
        "withholding tax",
        "accrual",
    )

    _CORE_MEASURE_TERMS = (
        "revenue",
        "sales",
        "turnover",
        "gross profit",
        "net profit",
        "net loss",
        "loss",
        "cash flow",
        "operating",
        "borrowing",
        "debt",
        "satisfaction",
        "order",
        "volume",
        "headcount",
        "production",
    )

    def plan(
        self,
        tasks: list[AnalysisTask],
        results: list[AnalysisResult],
        index: DocumentIndex,
        *,
        preferred_metrics: list[str] | None = None,
        insights: list[Insight] | None = None,
        report_plan: ReportPlan | None = None,
        analysis_focus: str | None = None,
        maximum: int = 10,
    ) -> list[ChartPlan]:
        valid_tasks = {result.task_id: result for result in results if result.result is not None and result.evidence}
        output: list[ChartPlan] = []
        seen_series: set[tuple[str, ...]] = set()
        seen_metrics: set[str] = set()
        chart_type_counts: Counter[ChartType] = Counter()

        focus_terms = [w.casefold() for w in re.findall(r"\b\w{3,}\b", analysis_focus or "")]
        insight_text = " ".join(
            f"{item.title} {item.narrative}"
            for item in (insights or [])
            if item.importance >= 0.6
        ).casefold()
        section_text = " ".join(
            f"{sec.title} {sec.purpose}"
            for sec in (report_plan.sections if report_plan else [])
        ).casefold()

        # Score all valid tasks generically using multi-criteria evaluation
        scored_tasks: list[tuple[float, AnalysisTask, list[Observation], list[str], str, str | None, str | None]] = []

        for task in tasks:
            supported_type = self._MAPPING.get(task.analysis_type)
            if not supported_type or task.id not in valid_tasks:
                continue

            identifiers = list(task.observation_query.get("observation_ids", []))
            observations = [index.get(identifier) for identifier in identifiers]
            observations = [item for item in observations if item and item.value is not None and is_meaningful_metric(item)]
            if len(observations) < 2:
                continue

            x_metric = task.required_metrics[0] if task.required_metrics else None
            y_metric = task.required_metrics[1] if len(task.required_metrics) > 1 else x_metric

            if supported_type == "scatter":
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

            score = self._score_task_candidate(
                task,
                observations,
                valid_tasks[task.id],
                focus_terms,
                insight_text,
                section_text,
            )
            scored_tasks.append((score, task, observations, identifiers, supported_type, x_metric, y_metric))

        # Select top task charts
        for _, task, observations, identifiers, _, x_metric, y_metric in sorted(
            scored_tasks, key=lambda item: item[0], reverse=True
        ):
            series_key = tuple(sorted(identifiers))
            if series_key in seen_series:
                continue

            chart_type = self._select_chart_type(task, observations, chart_type_counts)
            seen_series.add(series_key)
            seen_metrics.update(metric_key(item) for item in observations)
            chart_type_counts[chart_type] += 1
            pages = sorted(
                {source.page for identifier in identifiers if (item := index.get(identifier)) for source in item.evidence}
            )
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

        # Fill remaining slots with generic-scored reported series
        if len(output) < maximum:
            output.extend(
                self._reported_series_charts(
                    index,
                    seen_metrics=seen_metrics,
                    preferred_metrics=preferred_metrics or [],
                    priority_metrics=[metric for task in tasks for metric in task.required_metrics],
                    focus_terms=focus_terms,
                    insight_text=insight_text,
                    section_text=section_text,
                    maximum=maximum - len(output),
                    chart_type_counts=chart_type_counts,
                )
            )
        return output

    @classmethod
    def _score_task_candidate(
        cls,
        task: AnalysisTask,
        observations: list[Observation],
        task_result: AnalysisResult,
        focus_terms: list[str],
        insight_text: str,
        section_text: str,
    ) -> float:
        score = float(task.priority)
        task_text = f"{task.title} {task.reason} {' '.join(task.required_metrics)}".casefold()

        # 1. User analysis focus relevance
        score += sum(3.0 for term in focus_terms if term in task_text)

        # 2. Metric relevance to high-importance insights and report sections
        metric_terms = {item.metric_canonical.casefold() for item in observations if item.metric_canonical}
        metric_terms.update(item.metric_original.casefold() for item in observations if item.metric_original)
        score += sum(2.5 for term in metric_terms if len(term) > 3 and term in insight_text)
        score += sum(2.0 for term in metric_terms if len(term) > 3 and term in section_text)

        # 3. Multi-period comparison depth (>= 3 periods preferred)
        distinct_periods = {item.period for item in observations if item.period}
        if len(distinct_periods) >= 3:
            score += 3.0
        elif len(distinct_periods) == 2:
            score += 1.0

        # 4. Evidence completeness and confidence
        avg_confidence = sum(item.confidence for item in observations) / max(len(observations), 1)
        score += avg_confidence * 2.0
        distinct_pages = len({source.page for item in observations for source in item.evidence})
        score += min(distinct_pages, 4) * 0.5

        # 5. Clear conclusion support (values vary rather than flatline)
        values = [float(item.value) for item in observations if item.value is not None]
        if values and max(values) != min(values):
            score += 1.5

        # 6. Prioritise core measures and downweight peripheral items
        for term in metric_terms:
            if any(p in term for p in cls._PERIPHERAL_TERMS):
                score -= 5.0
            elif any(c in term for c in cls._CORE_MEASURE_TERMS):
                score += 3.0

        return score

    def _reported_series_charts(
        self,
        index: DocumentIndex,
        *,
        seen_metrics: set[str],
        preferred_metrics: list[str],
        priority_metrics: list[str],
        focus_terms: list[str],
        insight_text: str,
        section_text: str,
        maximum: int,
        chart_type_counts: Counter[ChartType],
    ) -> list[ChartPlan]:
        """Visualise safe reported series prioritized by generic multi-criteria scoring."""
        preferred = [name.casefold().strip() for name in preferred_metrics if name.strip()]
        priority = [name.casefold().strip() for name in priority_metrics if name.strip()]
        candidates: list[tuple[float, str, list[Observation]]] = []

        for metric in index.metrics():
            if metric in seen_metrics or metric in {"page", "pages"}:
                continue
            observations = index.for_metric(metric)
            if not observations or not is_meaningful_metric(observations[0]):
                continue
            if conflicting_groups(observations):
                continue
            series = best_period_series(observations)
            if len(series) < 2 or any(not item.evidence for item in series):
                continue

            score = self._score_series_candidate(
                metric,
                series,
                focus_terms=focus_terms,
                insight_text=insight_text,
                section_text=section_text,
                preferred=preferred,
                priority=priority,
            )
            candidates.append((score, metric, series))

        output: list[ChartPlan] = []
        for _, metric, series in sorted(candidates, key=lambda item: item[0], reverse=True)[:maximum]:
            identifiers = [item.id for item in series]
            pages = sorted({source.page for item in series for source in item.evidence})
            label = display_metric_name(series[0])
            title = label
            default_type = self._select_period_chart_type(series, chart_type_counts)
            chart_type_counts[default_type] += 1
            available_types: list[ChartType] = ["line", "bar", "table"]
            if len(series) >= 4 and all(float(item.value) >= 0 for item in series if item.value is not None):
                available_types.insert(2, "area")
            output.append(
                ChartPlan(
                    id=stable_id("chart", "reported_series", metric, *identifiers),
                    title=f"{title} — Reported Values",
                    chart_type=default_type,
                    question="How do the directly reported values compare across compatible periods?",
                    observation_ids=identifiers,
                    source_pages=pages,
                    available_chart_types=available_types,
                    x_metric=metric,
                    y_metric=metric,
                    x_axis_title="Period",
                    y_axis_title=self._metric_title(label, series),
                )
            )
        return output

    @classmethod
    def _score_series_candidate(
        cls,
        metric: str,
        series: list[Observation],
        *,
        focus_terms: list[str],
        insight_text: str,
        section_text: str,
        preferred: list[str],
        priority: list[str],
    ) -> float:
        metric_cf = metric.casefold()
        score = 0.0

        # User analysis focus relevance
        score += sum(3.0 for term in focus_terms if term in metric_cf)

        # Profile and analysis relevance
        if any(name in metric_cf or metric_cf in name for name in preferred):
            score += 2.0
        if any(name in metric_cf or metric_cf in name for name in priority):
            score += 1.5

        # Insight and report relevance
        if len(metric_cf) > 3 and metric_cf in insight_text:
            score += 2.5
        if len(metric_cf) > 3 and metric_cf in section_text:
            score += 2.0

        # Comparable periods depth
        distinct_periods = {item.period for item in series if item.period}
        if len(distinct_periods) >= 3:
            score += 3.0
        elif len(distinct_periods) == 2:
            score += 1.0

        # Confidence and page breadth
        avg_confidence = sum(item.confidence for item in series) / len(series)
        score += avg_confidence * 2.0
        distinct_pages = len({source.page for item in series for source in item.evidence})
        score += min(distinct_pages, 4) * 0.5

        # Non-flatline check
        values = [float(item.value) for item in series if item.value is not None]
        if values and max(values) != min(values):
            score += 1.0

        # Peripheral penalty vs core boost
        if any(p in metric_cf for p in cls._PERIPHERAL_TERMS):
            score -= 5.0
        elif any(c in metric_cf for c in cls._CORE_MEASURE_TERMS):
            score += 3.0

        return score

    def _select_chart_type(
        self,
        task: AnalysisTask,
        observations: list[Observation],
        chart_type_counts: Counter[ChartType],
    ) -> ChartType:
        """Choose the most truthful view, then balance equally valid period charts."""
        if task.analysis_type in {"pearson_correlation", "spearman_correlation"}:
            return "scatter"
        if task.analysis_type == "contribution_share":
            if self._is_complete_share(observations):
                return "pie"
            return self._category_chart_type(task, observations)
        if task.analysis_type in {"rank_values", "compare_categories"} or task.required_dimensions:
            return self._category_chart_type(task, observations)
        return self._select_period_chart_type(observations, chart_type_counts)

    @staticmethod
    def _category_chart_type(task: AnalysisTask, observations: list[Observation]) -> ChartType:
        dimension = task.required_dimensions[0] if task.required_dimensions else None
        labels = [
            str(item.dimensions.get(dimension) or item.entity or item.period or item.metric_original)
            for item in observations
        ]
        if len(labels) >= 5 or any(len(label) > 14 for label in labels):
            return "horizontal_bar"
        return "bar"

    @staticmethod
    def _select_period_chart_type(
        observations: list[Observation],
        chart_type_counts: Counter[ChartType],
    ) -> ChartType:
        periods = {item.period for item in observations if item.period}
        if len(periods) <= 3:
            return "bar"
        choices: list[ChartType] = ["line", "bar"]
        values = [float(item.value) for item in observations if item.value is not None]
        if len(periods) >= 4 and values and all(value >= 0 for value in values):
            choices.append("area")
        preference = {"line": 0, "bar": 1, "area": 2}
        return min(choices, key=lambda chart_type: (chart_type_counts[chart_type], preference[chart_type]))

    @staticmethod
    def _is_complete_share(observations: list[Observation]) -> bool:
        values = [float(item.value) for item in observations if item.value is not None]
        if not (2 <= len(values) <= 8) or any(value < 0 for value in values):
            return False
        units = {item.unit for item in observations if item.unit}
        return units == {"percent"} and 98.0 <= sum(values) <= 102.0

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
            choices: list[ChartType] = ["bar", "horizontal_bar", "table"]
            if ChartPlanner._is_complete_share(observations):
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
