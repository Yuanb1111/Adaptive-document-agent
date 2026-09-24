"""Resolve insight-to-input links without guessing from metric labels or pages."""

from adaptive_document_agent.models import PipelineResult


def insight_inputs(result: PipelineResult) -> dict[str, list[str]]:
    by_task = {item.task_id: item.input_observation_ids for item in result.analysis_results}
    available = {item.id for item in result.observations}
    return {item.id: list(dict.fromkeys(
        oid for task_id in item.result_ids for oid in by_task.get(task_id, []) if oid in available
    )) for item in result.insights}
