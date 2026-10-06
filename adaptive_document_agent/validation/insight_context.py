"""Require generated findings to retain explicitly extracted source scope.

This checks a source-copy contract, not the meaning of a metric. The model may
explain a measure, but must not silently drop the parent row or category that
identifies it. Rejected prose stays in the technical audit, never in the report.
"""

import json
import re

from adaptive_document_agent.models import AnalysisResult, Insight, Observation, ValidationIssue


def _key(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def source_scope_qualifiers(item: Observation) -> list[str]:
    """Use retained hierarchy and category values, without assigning meanings."""
    values = [item.parent_section or item.dimensions.get("section", "")]
    dimensions = item.category_dimensions or {
        key: value for key, value in item.dimensions.items()
        if key not in {"section", "table_context", "column_role", "period_basis"}
    }
    values.extend(dimensions.values())
    return list(dict.fromkeys(" ".join(value.split()).strip(" :;,-")
                             for value in values if value and _key(value)))


def qualified_metric_label(item: Observation) -> str:
    label = " ".join(item.metric_original.split()).strip()
    for qualifier in source_scope_qualifiers(item):
        if _key(qualifier) not in _key(label):
            label = f"{qualifier}: {label}"
    return label


def insight_context_errors(insight: Insight, linked: list[Observation]) -> list[str]:
    """Conservatively withhold prose that omits a linked row's explicit scope."""
    narrative = _key(insight.narrative)
    errors = []
    for item in linked:
        for qualifier in source_scope_qualifiers(item):
            # A title or hidden metric field cannot qualify a standalone claim
            # copied into an executive summary; the narrative must carry scope.
            if _key(qualifier) not in narrative:
                errors.append(f"The narrative omitted source scope {qualifier!r} for {item.id}")
    return list(dict.fromkeys(errors))


def validate_insight_contexts(
    insights: list[Insight], results: list[AnalysisResult], observations: list[Observation],
) -> tuple[list[Insight], list[ValidationIssue]]:
    """Validate newly generated or saved insights offline; never rewrite facts."""
    by_task = {item.task_id: item for item in results}
    by_id = {item.id: item for item in observations}
    accepted, issues = [], []
    for insight in insights:
        tasks = [by_task[rid] for rid in insight.result_ids if rid in by_task]
        ids = list(dict.fromkeys(oid for task in tasks for oid in task.input_observation_ids))
        linked = [by_id[oid] for oid in ids if oid in by_id]
        errors = insight_context_errors(insight, linked)
        if not errors:
            accepted.append(insight)
            continue
        issues.append(ValidationIssue(
            code="insight_source_context", stage="insight", severity="warning",
            message=json.dumps({"errors": errors, "insight": insight.model_dump(mode="json"),
                                "source_metrics": [qualified_metric_label(item) for item in linked]},
                               ensure_ascii=False),
            related_ids=[insight.id, *ids],
            evidence=[e for item in linked for e in item.evidence],
        ))
    return accepted, issues
