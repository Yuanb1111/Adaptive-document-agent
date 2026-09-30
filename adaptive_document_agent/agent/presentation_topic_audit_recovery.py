"""Revalidate retained model drafts after a compilation capability change."""
import json
from collections import Counter

from adaptive_document_agent.models import PresentationTopic, PresentationTopicSelection, ValidationIssue
from .presentation_topic_selector import PresentationTopicSelector, series_directory


def recover_audited_topics(result):
    if not result.presentation_topics:
        return False
    _, lookup = series_directory(result)
    retained = {topic.id for topic in result.presentation_topics.topics}
    additions, drafts = [], []
    for warning in result.validation_warnings:
        if warning.code != "presentation_topic_validation":
            continue
        try:
            audit = json.loads(warning.message)
            if audit.get("phase") != "initial":
                continue
            drafts.append(PresentationTopic.model_validate(audit["topic"]))
        except (ValueError, KeyError, TypeError):
            continue
    counts = Counter(topic.id for topic in drafts)
    for topic in drafts:
        if topic.id in retained or counts[topic.id] != 1:
            continue
        try:
            PresentationTopicSelector._validate(PresentationTopicSelection(topics=[topic]), lookup)
        except (ValueError, KeyError, TypeError):
            continue
        retained.add(topic.id)
        additions.append(topic)
    if not additions:
        return False
    snapshot = result.model_copy(deep=True)
    topics = [*snapshot.presentation_topics.topics, *additions]
    selected = {sid for topic in topics for sid in topic.series_ids}
    snapshot.presentation_topics = PresentationTopicSelection(topics=topics,
        omissions=[o for o in snapshot.presentation_topics.omissions if o.series_id not in selected])
    from .topic_plan_compiler import compile_topic_plan
    try:
        previous = snapshot.presentation_plan
        snapshot.presentation_plan = None
        from .chart_planner import ChartPlanner
        from adaptive_document_agent.document_model import DocumentIndex
        snapshot.charts = ChartPlanner().plan([], [], DocumentIndex(snapshot.observations),
            requested_series=[lookup[sid] for sid in selected], only_requested=True)
        plan = compile_topic_plan(snapshot)
        if previous:
            plan.company = previous.company.model_copy(deep=True)
            from .presentation_topic_scope_recovery import _WITHHELD_PREFIX, withheld_topic_ids, validate_selected_topic_claims
            plan.editorial_notes.extend(n for n in previous.editorial_notes if n.startswith(_WITHHELD_PREFIX))
            withheld = withheld_topic_ids(plan)
            for slide in plan.slides:
                if slide.slide_type == "analysis" and slide.theme_id in withheld:
                    slide.title = slide.analytical_question
            from .presentation_summary_selection import rebuild_selected_topic_summary
            rebuild_selected_topic_summary(snapshot, plan)
            plan = validate_selected_topic_claims(plan, snapshot)
        from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
        PresentationPlanValidator().validate(plan, snapshot)
    except ValueError:
        return False  # Transactional: preserve the old plan and every rejection.
    result.presentation_topics = snapshot.presentation_topics
    result.presentation_plan = plan
    result.charts = snapshot.charts
    result.validation_warnings = snapshot.validation_warnings
    result.validation_warnings.append(ValidationIssue(code="presentation_audited_topics_recovered",
        stage="presentation", severity="info", related_ids=[t.id for t in additions],
        message="Retained model-selected drafts revalidated and compiled from their exact original series without a model request."))
    return True
