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
    score_chartability,
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


_NUMERIC_CATEGORY_PATTERN = re.compile(r"^\s*[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\s*$")


def is_valid_scatter_candidate(
    task: AnalysisTask,
    observations: list[Observation],
    x_metric: str | None = None,
    y_metric: str | None = None,
) -> bool:
    """Validate that scatter charts are only used for genuine continuous relationships.

    Requirements:
    - x-axis and y-axis are clearly meaningful numeric variables (not arbitrary numbers/codes).
    - Both axes have explicit labels.
    - The relationship between them is explicitly explained.
    - Not arbitrary numeric categories (such as 70.901, 131.843, etc.).
    - Fallback to line, bar, or table if continuous relationship is not well-defined.
    """
    x_m = x_metric or (task.required_metrics[0] if task.required_metrics else None)
    y_m = y_metric or (task.required_metrics[1] if len(task.required_metrics) > 1 else None)
    if not x_m or not y_m:
        return False
    if x_m.strip().casefold() == y_m.strip().casefold():
        return False

    # Reject arbitrary numeric literals, ratios, or table coordinates for metric names
    if _NUMERIC_CATEGORY_PATTERN.match(x_m) or _NUMERIC_CATEGORY_PATTERN.match(y_m):
        return False

    # Must contain alphabetic characters indicating a genuine metric name
    if not re.search(r"[A-Za-z\u4e00-\u9fa5]", x_m) or not re.search(r"[A-Za-z\u4e00-\u9fa5]", y_m):
        return False

    # Explicit labels check
    x_title = ChartPlanner._x_title(task, observations)
    y_title = ChartPlanner._y_title(task, observations)
    if not x_title or not y_title:
        return False
    if x_title.casefold() in {"category", "unknown", "first metric"} or y_title.casefold() in {"unknown"}:
        return False
    if _NUMERIC_CATEGORY_PATTERN.match(x_title) or _NUMERIC_CATEGORY_PATTERN.match(y_title):
        return False

    # Check that relationship is explicitly explained
    task_desc = getattr(task, "description", "") or getattr(task, "question", "")
    task_reason = getattr(task, "reason", "")
    explanation = f"{task_desc} {task_reason}".strip()
    if len(explanation) < 8:
        return False
    has_rel_word = bool(
        re.search(r"(?i)\b(correlat|relationship|versus|vs\.?|against|impact|depend|link|interact|trend)\b", explanation)
    )
    has_metrics = (x_m.casefold() in explanation.casefold()) or (y_m.casefold() in explanation.casefold())
    if not (has_rel_word or has_metrics):
        return False

    # Pairs check
    pairs = paired_observations(observations, x_m, y_m)
    if len(pairs) < 5:
        return False

    x_vals = [float(p[0].value) for p in pairs if p[0].value is not None]
    y_vals = [float(p[1].value) for p in pairs if p[1].value is not None]
    if len(set(x_vals)) < 3 or len(set(y_vals)) < 3:
        return False

    # Check for arbitrary numeric categories in observations
    for left, right in pairs:
        for dim_val in (*left.dimensions.values(), *right.dimensions.values()):
            if isinstance(dim_val, str) and _NUMERIC_CATEGORY_PATTERN.match(dim_val) and "." in dim_val:
                return False

    return True


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
                if not x_metric or not y_metric or not is_valid_scatter_candidate(task, observations, x_metric, y_metric):
                    # Fallback: do not use scatter for arbitrary numeric categories or ill-defined relationships
                    distinct_periods = {item.period for item in observations if item.period}
                    if len(distinct_periods) >= 2:
                        coherent_series = best_period_series(observations)
                        if len(coherent_series) < 2:
                            continue
                        observations = coherent_series
                    identifiers = [item.id for item in observations]
                else:
                    pairs = paired_observations(observations, x_metric, y_metric)
                    if len(pairs) < 5:
                        continue
                    observations = [item for pair in pairs for item in pair]
                    identifiers = [item.id for item in observations]
            else:
                distinct_periods = {item.period for item in observations if item.period}
                if len(distinct_periods) >= 2:
                    coherent_series = best_period_series(observations)
                    if len(coherent_series) < 2:
                        continue
                    observations = coherent_series
                identifiers = [item.id for item in observations]

            chartability = score_chartability(observations)
            if not chartability.is_chartable:
                continue

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

        # 5. AnalysisResult validity and confidence
        if task_result.result is not None:
            score += 1.5 + float(task_result.confidence) * 1.5
        if task_result.warnings:
            score -= min(len(task_result.warnings), 3) * 0.5

        # 6. Clear conclusion support (values vary rather than flatline)
        values = [float(item.value) for item in observations if item.value is not None]
        if values and max(values) != min(values):
            score += 1.5

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

            chartability = score_chartability(series)
            if not chartability.is_chartable:
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

        return score

    def _select_chart_type(
        self,
        task: AnalysisTask,
        observations: list[Observation],
        chart_type_counts: Counter[ChartType],
    ) -> ChartType:
        """Choose the most truthful view, then balance equally valid period charts."""
        if task.analysis_type in {"pearson_correlation", "spearman_correlation"}:
            x_m = task.required_metrics[0] if task.required_metrics else None
            y_m = task.required_metrics[1] if len(task.required_metrics) > 1 else None
            if is_valid_scatter_candidate(task, observations, x_m, y_m):
                return "scatter"
            # Fallback to line, bar, or table if continuous relationship is not well-defined
            periods = {item.period for item in observations if item.period}
            if len(periods) >= 2:
                return self._select_period_chart_type(observations, chart_type_counts)
            return self._category_chart_type(task, observations)
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
            x_m = task.required_metrics[0] if task.required_metrics else None
            y_m = task.required_metrics[1] if len(task.required_metrics) > 1 else None
            if is_valid_scatter_candidate(task, observations, x_m, y_m):
                return ["scatter", "table"]
            periods = {item.period for item in observations if item.period}
            if len(periods) >= 2:
                return ["line", "bar", "table"]
            return ["bar", "horizontal_bar", "table"]
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
    def _y_title(task: AnalysisTask, observations: list[Observation]) -> str:
        if len(task.required_metrics) > 1:
            return task.required_metrics[1].replace("_", " ").title()
        if observations:
            return (observations[0].metric_original or observations[0].canonical_name or "Value").replace("_", " ").title()
        return "Value"

    @staticmethod
    def _metric_title(metric: str | None, observations: list[Observation]) -> str:
        name = (metric or "Value").replace("_", " ").title()
        currencies = sorted({item.currency for item in observations if item.currency})
        units = sorted({item.unit for item in observations if item.unit and item.unit != "currency"})
        suffix = " / ".join([*currencies, *units])
        return f"{name} ({suffix})" if suffix else name
