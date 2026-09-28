"""Bind every model-selected topic to a paginated summary and complete evidence."""

from adaptive_document_agent.models import PipelineResult, PresentationPlan
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator


def rebuild_selected_topic_summary(result: PipelineResult, plan: PresentationPlan) -> bool:
    """Rebuild a compiled summary in model order, without evidence-size ranking.

    Rebuild before claim checks, respecting repairs already present in current
    analysis claims and retaining full model takeaways when the compiler only
    shortened a long title for layout.
    This also restores topics omitted by older cached four-item summaries.
    It does not authorize unsupported claims; normal validation still applies.
    Raw observations and model topic selections are unchanged.
    """
    selection = result.presentation_topics
    summary = next((slide for slide in plan.slides if slide.slide_type == "executive_summary"), None)
    if not selection or not summary:
        return False
    themes = {theme.id: theme for theme in plan.themes}
    observations = {item.id: item for item in result.observations}
    charts = {chart.id: chart for chart in result.charts}
    analyses = {slide.theme_id: slide for slide in plan.slides
                if slide.slide_type == "analysis" and slide.slide_role == "overview"}
    from .presentation_topic_selector import series_directory

    _, series = series_directory(result)
    inputs_by_task = {item.task_id: set(item.input_observation_ids) for item in result.analysis_results}
    bullets: list[str] = []
    bullet_inputs: list[list[str]] = []
    chosen_insights = []
    for topic in selection.topics:
        theme = themes.get(topic.id)
        if theme is None:
            # Recovery has already recorded unavailable/invalid selected topics.
            continue
        ids = list(dict.fromkeys([
            *theme.observation_ids,
            *(oid for cid in theme.chart_ids if cid in charts
              for oid in (*charts[cid].observation_ids, *charts[cid].total_observation_ids)),
            # Earlier presentation alignment may have consolidated repeated
            # sources. Keep their original records as summary evidence too.
            *(item.id for sid in topic.series_ids for item in series.get(sid, [])),
        ]))
        ids = [oid for oid in ids if oid in observations and observations[oid].evidence
               and observations[oid].validation_status in {"valid", "partially_valid"}]
        if not ids:
            continue
        source_fields = [
            str(value) for oid in ids for value in (
                observations[oid].value, observations[oid].raw_value,
                observations[oid].period, observations[oid].entity, observations[oid].dimensions,
            ) if value is not None
        ]
        source_fields.extend(f"{observations[oid].value}%" for oid in ids
                             if observations[oid].unit == "percent"
                             or observations[oid].unit_family == "percentage")
        # Parsing each field separately avoids merging a grouped raw amount
        # and the next field's year into one apparent numeric token.
        allowed = set().union(*(PresentationPlanValidator._numbers(value) for value in source_fields))
        # Legitimately sourced digits are permitted; an unsupported number
        # falls back to the same model-selected question, never another topic.
        text = next((text for text in (topic.takeaway, topic.title, topic.question)
                     if text.strip() and not (PresentationPlanValidator._numbers(text) - allowed)),
                    "Selected evidence")
        if not topic.takeaway:
            from .presentation_plan_recovery import PresentationPlanRecovery

            candidates = [item for item in result.insights
                          if item.id not in {chosen.id for chosen in chosen_insights}
                          and item.evidence and not PresentationPlanRecovery._is_calc_artifact(item.title)
                          and item.result_ids
                          and all(inputs_by_task.get(task_id) and inputs_by_task[task_id] <= set(ids)
                                  for task_id in item.result_ids)
                          and not (PresentationPlanValidator._numbers(item.title) - allowed)]
            if candidates:
                chosen = max(candidates, key=lambda item: (item.importance, item.confidence))
                chosen_insights.append(chosen)
                text = chosen.title
        # Distinguish a semantic repair from the compiler's routine title
        # shortening. Rebuilding cached summaries must never restore an old
        # denominator or overly broad period over a corrected analysis claim.
        compiled_title = next((copy for copy in (topic.takeaway, topic.title, topic.question)
                               if copy.strip() and not (PresentationPlanValidator._numbers(copy) - allowed)),
                              "Selected evidence")
        if len(compiled_title.split()) > 18 and not (PresentationPlanValidator._numbers(topic.title) - allowed):
            compiled_title = topic.title
        analysis = analyses.get(topic.id)
        was_repaired = bool(analysis and (analysis.title != compiled_title
                            or analysis.selection_reason and analysis.selection_reason != topic.rationale))
        if (analysis and analysis.title.strip() and was_repaired
                and not (PresentationPlanValidator._numbers(analysis.title) - allowed)):
            text = analysis.title
        bullets.append(text)
        bullet_inputs.append(ids)
    if not bullets:
        return False
    summary.bullets = bullets
    summary.bullet_observation_ids = bullet_inputs
    summary.insight_ids = [item.id for item in chosen_insights]
    summary.observation_ids = list(dict.fromkeys(oid for ids in bullet_inputs for oid in ids))
    summary.source_pages = sorted({e.page for oid in summary.observation_ids for e in observations[oid].evidence}
                                  | {e.page for item in chosen_insights for e in item.evidence})
    return True


def sync_selected_topic_summary_evidence(result: PipelineResult, plan: PresentationPlan) -> bool:
    """Add evidence bound by claim checks without rewriting their approved copy.

    A repair may retrieve additional reported shares or period endpoints. The
    summary should cite them on this pass, rather than changing on the next
    cached replay. Only an already complete, correspondingly ordered topic
    summary is eligible; this operation cannot add or revive a claim.
    """
    summary = next((slide for slide in plan.slides if slide.slide_type == "executive_summary"), None)
    if not summary or not summary.bullets or len(summary.bullet_observation_ids) != len(summary.bullets):
        return False
    candidate = plan.model_copy(deep=True)
    if not rebuild_selected_topic_summary(result, candidate):
        return False
    rebuilt = next(slide for slide in candidate.slides if slide.slide_type == "executive_summary")
    if (len(rebuilt.bullets) != len(summary.bullets)
            or any(not old or not set(old) <= set(new)
                   for old, new in zip(summary.bullet_observation_ids, rebuilt.bullet_observation_ids))):
        return False
    observations = {item.id: item for item in result.observations}
    pages = sorted({e.page for oid in rebuilt.observation_ids for e in observations[oid].evidence}
                   | {e.page for item in result.insights if item.id in summary.insight_ids for e in item.evidence})
    changed = (summary.bullet_observation_ids != rebuilt.bullet_observation_ids
               or summary.observation_ids != rebuilt.observation_ids or summary.source_pages != pages)
    summary.bullet_observation_ids = rebuilt.bullet_observation_ids
    summary.observation_ids = rebuilt.observation_ids
    summary.source_pages = pages
    return changed
