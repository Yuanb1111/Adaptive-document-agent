"""Withhold unsupported optional closing copy without discarding valid evidence."""

import json

from adaptive_document_agent.models import Observation, PipelineResult, PresentationPlan, PresentationSlide, ValidationIssue


def closing_claim_errors(statement: str, records: list[Observation], result: PipelineResult) -> list[str]:
    from adaptive_document_agent.validation.claim_validator import ClaimValidator
    from adaptive_document_agent.validation.scoped_narrative_values import scoped_value_errors
    from .presentation_insight_recovery import _numeric_support

    candidate = PresentationSlide(id="slide_risks", slide_type="risks", title="Conclusions",
                                 bullets=[statement], observation_ids=[o.id for o in records])
    errors = [issue.message for issue in ClaimValidator().validate_slide(candidate, records)
              if issue.severity == "error"]
    errors.extend(scoped_value_errors(candidate, records, result.observations))
    if not _numeric_support(statement, records):
        errors.append("Closing numbers must retain their source values or explicitly typed, validated calculations.")
    return errors


def withhold_cached_closing_claims(result: PipelineResult, plan: PresentationPlan) -> list[str]:
    """Independently check each cached conclusion using its own retained inputs.

    Original insights, results and observations remain unchanged. Withdrawn
    display copy stays in the audit; unsupported numeric claims on analytical
    pages still fail the normal export gate.
    """
    from adaptive_document_agent.validation.presentation_provenance import insight_inputs

    by_id = {o.id: o for o in result.observations}
    links = insight_inputs(result)
    notes = []
    for slide in list(plan.slides):
        if slide.slide_type != "risks":
            continue
        scoped = len(slide.bullet_observation_ids) == len(slide.bullets)
        retained, scopes = [], []
        for index, statement in enumerate(slide.bullets):
            ids = (slide.bullet_observation_ids[index] if scoped else list(dict.fromkeys([
                *slide.observation_ids, *(oid for iid in slide.insight_ids for oid in links.get(iid, []))])))
            errors = closing_claim_errors(statement, [by_id[oid] for oid in ids if oid in by_id], result)
            if not errors:
                retained.append(statement)
                scopes.append(list(ids))
                continue
            audit = json.dumps({"slide_id": slide.id, "statement": statement, "errors": errors},
                               ensure_ascii=False, sort_keys=True)
            warning = ValidationIssue(code="presentation_closing_claim_withheld", severity="warning",
                                      stage="presentation", message=audit, related_ids=[slide.id, *ids])
            if warning not in result.validation_warnings:
                result.validation_warnings.append(warning)
            notes.append(f"Slide {slide.id}: withheld unsupported closing copy; original retained in audit.")
        if len(retained) != len(slide.bullets):
            slide.bullets = retained
            slide.bullet_observation_ids = scopes
            if not retained:
                plan.slides.remove(slide)
    if notes:
        plan.editorial_notes = list(dict.fromkeys([*plan.editorial_notes, *notes]))
        if plan.editorial_status != "degraded":
            plan.editorial_status = "needs_review"
    return notes
