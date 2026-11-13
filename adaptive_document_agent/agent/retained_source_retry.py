"""Repair rejected retained copy while preserving the completed report shell."""
import json

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from .retained_analysis import (
    SELECTION_CODE, RetainedAnalysisSelection, selected_record, selection_context,
    fingerprint, findings, _validate_selection,
)


def repair_retained_source_copy(gateway, result, previous=None):
    from .retained_selection_feedback import retain_selection_feedback
    from .retained_page_sources import (
        writer_context, source_row_assurance, validate_authored_pages,
        page_bindings, context_evidence_pages,authored_message,
    )
    from .retained_page_revision import revise_retained_pages
    issue = retain_selection_feedback(result if previous is None else previous,
                                      live_review=previous is None)
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
    linked = findings(result, allow_new_copy=True)
    from .reported_source_context import reported_source_components,observation_context_labels,source_context_paragraphs
    from adaptive_document_agent.services.calendar_claims import bound_period_dates,literal_calendar_dates
    original_parts={}
    for decision in selection.decisions:
        if decision.decision!='include' or decision.page is None:
            continue
        ids=linked[decision.insight_id][1] | set(decision.page.companion_ids)
        periods=[o.period for o in result.observations if o.id in ids and o.period]
        dates=set().union(*(literal_calendar_dates(q.text) for q in decision.page.all_context_evidence))
        text=authored_message(decision.page,[*periods,*dates])
        original_parts[decision.insight_id]=reported_source_components(
            text,decision.page.all_context_evidence,periods=[*periods,*dates],
            labels=observation_context_labels([o for o in result.observations if o.id in ids]),
            declared=decision.page.source_context)
        main,parts=original_parts[decision.insight_id]
        original_parts[decision.insight_id]=(main,source_context_paragraphs(parts))
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
        title, copy, ids, reported = page_bindings(page, insight, primary, context, result,
                                                  with_source_context=True)
        if not set(slide.observation_ids) <= ids:
            raise ValueError('Local copy correction removed its compiled observation scope.')
        # Native source assurance can append a separate coverage bullet. Its
        # evidence bindings must survive an edit of the authored main copy.
        old=original_parts[iid]
        owned_count=1+len(old[1])
        if not slide.bullets or slide.bullets[:owned_count] != [old[0],*old[1]]:
            raise ValueError('Local copy correction requires the original authored first bullet.')
        slide.title, slide.message = title, copy
        slide.bullets = [copy,*reported,*slide.bullets[owned_count:]]
        slide.observation_ids = sorted(ids)
        slide.bullet_observation_ids = [sorted(ids),*[[] for _ in reported],
                                       *slide.bullet_observation_ids[owned_count:]]
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
