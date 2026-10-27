"""Place existing source-bound explanations beside their exact chart inputs."""
from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator

from .insight_source_context import SourceExcerpt, matched_driver_evidence
from .presentation_insight_recovery import _linked_findings


def attach_topic_explanations(plan, result):
    """Keep the selected question; never infer links from names or shared pages.

    The model already authored and prioritized these findings. An explanation
    can appear only where all its task inputs are displayed and its literal
    source quote still exists. Every attachment passes the normal plan gates.
    Unsupported copy stays in the audit rather than replacing the question.
    """
    from adaptive_document_agent.validation.narrative_plan_validator import expanded_observation_ids
    charts = {c.id: c for c in result.charts}
    pages = {p.page_number: p for p in result.document.pages}
    findings = []
    for insight, ids, copy in _linked_findings(result):
        page = pages.get(insight.driver_source_page)
        if not insight.driver or page is None or copy != insight.narrative:
            continue
        source = matched_driver_evidence(insight.driver_quote, insight.driver_source_page,
            [SourceExcerpt(page.page_number, page.text, 0, page.extraction_quality)])
        if source is not None and matched_driver_evidence(insight.driver_quote,
                insight.driver_source_page, [], legacy_evidence=insight.evidence) is not None:
            findings.append((insight, ids, copy))
    findings.sort(key=lambda row: (-row[0].importance, -row[0].confidence))
    for position, slide in enumerate(list(plan.slides)):
        if slide.slide_type != 'analysis' or not slide.analytical_question or slide.bullets:
            continue
        visible = expanded_observation_ids(slide, charts)
        candidates = [(i, ids, copy) for i, ids, copy in findings if ids <= visible]
        covered = set()
        for insight, ids, copy in candidates:
            if ids <= covered or len(plan.slides[position].bullets) >= 2:
                continue
            trial = plan.model_copy(deep=True)
            candidate = trial.slides[position]
            candidate.bullets.append(copy)
            candidate.bullet_observation_ids.append(sorted(ids))
            candidate.insight_ids.append(insight.id)
            candidate.source_pages = sorted(set(candidate.source_pages) | {e.page for e in insight.evidence})
            try:
                PresentationPlanValidator().validate(trial, result)
            except ValueError as exc:
                result.validation_warnings.append(ValidationIssue(code='presentation_explanation_withheld',
                    severity='warning', stage='presentation', related_ids=[slide.id, insight.id], message=str(exc)))
                continue
            plan.slides[position] = candidate
            covered.update(ids)
    return plan
