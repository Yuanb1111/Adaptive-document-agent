"""Recompile saved model-selected questions offline without approving new evidence."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from adaptive_document_agent.models import PipelineResult
from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.agent.presentation_topic_scope_recovery import withheld_topic_ids
from adaptive_document_agent.agent.report_audit_scope import needs_report_audit_scope


def replay(path):
    result = PipelineResult.model_validate_json(Path(path).read_text(encoding='utf-8'))
    source = deepcopy((result.observations, result.presentation_topics, result.insights, result.llm_usage))
    plan = PresentationPlanRecovery().from_selected_topics(result)
    assert (result.observations, result.presentation_topics, result.insights, result.llm_usage) == source
    result.presentation_plan = plan
    return dict(planning_origin=plan.planning_origin, retained_topics=[t.id for t in plan.themes],
        question_only_topics=sorted(withheld_topic_ids(plan)),
        source_and_model_selections_unchanged=True, model_calls=0,
        new_audit_scope_review_required=needs_report_audit_scope(result), end_to_end_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis_json')
    print(json.dumps(replay(parser.parse_args().analysis_json), indent=2))
