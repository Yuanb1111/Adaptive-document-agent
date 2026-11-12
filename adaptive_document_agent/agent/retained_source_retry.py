"""Repair rejected retained copy while preserving the completed report shell."""
import json

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from .retained_analysis import (
    SELECTION_CODE, RetainedAnalysisSelection, selected_record, selection_context,
    fingerprint, findings, _validate_selection,
)


def repair_retained_source_copy(gateway, result, previous):
    from .retained_selection_feedback import retain_selection_feedback
    from .retained_page_sources import (
        writer_context, source_row_assurance, validate_authored_pages,
        page_bindings, context_evidence_pages,
    )
    from .retained_page_revision import revise_retained_pages
    issue = retain_selection_feedback(previous)
    if issue is None:
        raise ValueError('The retained source correction has no bound reviewer feedback.')
    feedback = json.loads(issue.message)
    issues = feedback.get('earlier_page_issues', {})
    if not issues:
        raise ValueError('The source correction must identify rejected retained pages.')
    context = selection_context(result, source_authoring=True)
    packet, aliases = writer_context(context)
    packet['source_row_assurance'] = source_row_assurance(result, aliases)
    reverse = {value: key for key, value in aliases.items()}
    record = selected_record(result)
    selection = RetainedAnalysisSelection.model_validate(record['selection'])
    draft = selection.model_dump(mode='json')
    for decision in draft['decisions']:
        if decision['page']:
            decision['page']['companion_ids'] = [reverse.get(k, k) for k in decision['page']['companion_ids']]
    previous_contract = feedback['rejected'].get('diagnostic', '')
    revised = revise_retained_pages(gateway, result, packet, aliases, draft, issues,
                                   earlier_issues={iid: [previous_contract] for iid in issues}
                                   if previous_contract else None,
                                   preserve_numeric_inputs=True)
    for decision in selection.decisions:
        if decision.insight_id not in revised:
            continue
        page = revised[decision.insight_id]
        page.companion_ids = [aliases.get(k, k) for k in page.companion_ids]
        if not set(decision.page.companion_ids) <= set(page.companion_ids):
            raise ValueError('A local publication-copy correction cannot remove retained numeric inputs.')
        decision.page = page
    _validate_selection(selection, context)
    validate_authored_pages(selection, context, result)
    updated = {**record, 'input_fingerprint': fingerprint(context),
               'selection': selection.model_dump(mode='json', exclude_none=True)}
    result.validation_warnings.extend([issue, ValidationIssue(code=SELECTION_CODE,
        stage='presentation', severity='info', message=json.dumps(updated, ensure_ascii=False))])
    linked = findings(result, allow_new_copy=True)
    by_id = {o.id: o for o in result.observations}
    from adaptive_document_agent.services.source_citations import evidence_pages
    for slide in result.presentation_plan.slides:
        if slide.slide_type != 'analysis' or len(slide.insight_ids) != 1 or slide.insight_ids[0] not in revised:
            continue
        iid = slide.insight_ids[0]
        insight, primary, _ = linked[iid]
        page = next(d.page for d in selection.decisions if d.insight_id == iid)
        title, copy, ids = page_bindings(page, insight, primary, context, result)
        if not set(slide.observation_ids) <= ids:
            raise ValueError('Local copy correction removed its compiled observation scope.')
        # Native source assurance can append a separate coverage bullet. Its
        # evidence bindings must survive an edit of the authored main copy.
        if not slide.bullets or slide.bullets[0] != slide.message:
            raise ValueError('Local copy correction requires the original authored first bullet.')
        slide.title, slide.message = title, copy
        slide.bullets = [copy, *slide.bullets[1:]]
        slide.observation_ids = sorted(ids)
        slide.bullet_observation_ids[0] = sorted(ids)
        slide.section_title = slide.analytical_question = title
        slide.source_pages = sorted(set(evidence_pages(insight, [by_id[k] for k in ids], document=result.document))
                                    | context_evidence_pages(page, context, result))
        for theme in result.presentation_plan.themes:
            if theme.id == slide.theme_id:
                theme.title = theme.question = title
                theme.observation_ids = sorted(ids)
                theme.source_pages = list(slide.source_pages)
    PresentationPlanValidator().validate(result.presentation_plan, result)
    from adaptive_document_agent.services.presentation_editorial import stamp_editorial_review
    result.presentation_plan = stamp_editorial_review(result.presentation_plan, result, origin='repaired')
