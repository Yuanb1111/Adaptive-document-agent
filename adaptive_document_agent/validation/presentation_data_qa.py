"""Final unit, data density and chart-to-narrative checks before PPT export."""

import re

from adaptive_document_agent.document_model.metric_semantic_classifier import is_financial_statement_metric
from adaptive_document_agent.document_model.topic_matcher import is_positive_topic_mismatch
from adaptive_document_agent.extraction.column_roles import explicit_percentage, intrinsic_percentage
from adaptive_document_agent.models import PipelineResult


def validate_presentation_data(result: PipelineResult):
    from adaptive_document_agent.services.qa_reporter import QAItem

    issues = []
    for obs in result.observations:
        is_pct = obs.unit in {"%", "percent", "percentage"} or obs.unit_family == "percentage"
        source_labels = [e.row_label for e in obs.evidence if e.row_label]
        source_label = source_labels[0] if source_labels else re.sub(r"\s*%\s*$", "", obs.metric_original)
        monetary = is_financial_statement_metric(source_label) and not intrinsic_percentage(source_label)
        strong_pct = explicit_percentage(obs.raw_value) or intrinsic_percentage(source_label) or any(
            explicit_percentage(e.column_label) for e in obs.evidence
        )
        if monetary and ((is_pct and not strong_pct) or (not is_pct and "%" in obs.display_value)):
            issues.append(QAItem(
                code="monetary_percentage_mismatch", severity="CRITICAL", related_ids=[obs.id],
                message=f"Metric '{obs.metric_original}' is displayed as a percentage without source percentage evidence. Re-evaluate column {obs.column_id} in table {obs.effective_table_id}.",
            ))
        if is_pct and obs.value is not None and abs(obs.value) > 1000:
            issues.append(QAItem(
                code="implausible_percentage", severity="CRITICAL", related_ids=[obs.id],
                message=f"Metric '{obs.metric_original}' has implausible percentage {obs.value:g}%. Re-evaluate the source column role and alignment before export.",
            ))

    if not result.presentation_plan:
        return issues
    if result.presentation_plan.themes or any(s.theme_id or s.calculation_ids for s in result.presentation_plan.slides):
        from .narrative_plan_validator import validate_narrative_plan
        for error in validate_narrative_plan(result.presentation_plan, result):
            issues.append(QAItem(code="narrative_evidence_contract", severity="CRITICAL", message=error))
    observations = {o.id: o for o in result.observations}
    charts = {c.id: c for c in result.charts}
    seen = {}
    for slide in result.presentation_plan.slides:
        if slide.slide_type not in {"analysis", "executive_summary"}:
            continue
        chart_ids = set(slide.chart_ids) | {cid for b in slide.visual_blocks for cid in b.chart_ids}
        obs_ids = set(slide.observation_ids) | {oid for b in slide.visual_blocks for oid in b.observation_ids}
        for cid in chart_ids:
            chart = charts.get(cid)
            if chart:
                from adaptive_document_agent.services.composition_data import COMPOSITION_TYPES, composition_data
                requested_types = {chart.chart_type, *(b.chart_type for b in slide.visual_blocks if cid in b.chart_ids and b.chart_type)}
                for requested_type in requested_types & COMPOSITION_TYPES:
                    try:
                        composition_data(chart.model_copy(update={"chart_type": requested_type}),
                            [observations[oid] for oid in chart.observation_ids if oid in observations],
                            [observations[oid] for oid in chart.total_observation_ids if oid in observations])
                    except ValueError as exc:
                        issues.append(QAItem(code="invalid_composition_chart", severity="CRITICAL", slide_id=slide.id,
                            related_ids=[cid], message=str(exc)))
                obs_ids.update(chart.observation_ids)
                # Use positive mismatch evidence so an unfamiliar title is not
                # treated as proof that the source metric is wrong.
                titles = {chart.title, *(b.title for b in slide.visual_blocks if b.chart_ids == [cid] and b.title)}
                for title in titles:
                    chart_topic = slide.model_copy(update={"title": title, "message": "", "section_title": "", "bullets": []})
                    if any(is_positive_topic_mismatch(observations[oid], chart_topic)
                           for oid in chart.observation_ids if oid in observations):
                        issues.append(QAItem(code="chart_title_data_mismatch", severity="CRITICAL",
                            slide_id=slide.id, related_ids=[cid], message=f"Chart '{title}' does not match its linked metric data."))
            if cid not in slide.chart_ids:
                if not chart or any(oid not in observations for oid in chart.observation_ids):
                    issues.append(QAItem(code="chart_mismatch", severity="CRITICAL", slide_id=slide.id,
                        related_ids=[cid], message=f"Visual block on slide {slide.id} references missing chart data."))
                elif any(is_positive_topic_mismatch(observations[oid], slide) for oid in chart.observation_ids):
                    issues.append(QAItem(code="chart_topic_mismatch", severity="CRITICAL", slide_id=slide.id,
                        related_ids=[cid], message=f"Visual block chart {cid} does not match slide '{slide.title}'."))
        block_ids = {oid for b in slide.visual_blocks for oid in b.observation_ids} - set(slide.observation_ids)
        kpi_ids = {oid for b in slide.visual_blocks if b.role == "kpi" for oid in b.observation_ids}
        if any(is_positive_topic_mismatch(observations[oid], slide, is_supporting_kpi=oid in kpi_ids) for oid in block_ids if oid in observations):
            issues.append(QAItem(code="slide_topic_mismatch", severity="CRITICAL", slide_id=slide.id,
                related_ids=sorted(block_ids), message=f"Visual block table does not match slide '{slide.title}'."))
        if slide.slide_type != "analysis":
            continue
        numeric_ids = {oid for oid in obs_ids if oid in observations and observations[oid].value is not None}
        if len(numeric_ids) < 2:
            issues.append(QAItem(code="insufficient_analysis_content", severity="WARNING" if numeric_ids else "CRITICAL", slide_id=slide.id,
                message=f"Slide '{slide.title}' has fewer than two retained numeric observations for analysis."))
        signature = (frozenset(obs_ids), slide.slide_role, " ".join(slide.title.casefold().split()),
                     " ".join(slide.message.casefold().split()))
        if obs_ids and signature in seen:
            issues.append(QAItem(code="redundant_analysis_slide", severity="WARNING", slide_id=slide.id,
                message=f"Slide {slide.id} repeats the title, narrative and evidence of slide {seen[signature]}."))
        seen[signature] = slide.id
    return issues
