"""Place existing analytical continuations in appendices for explicit body limits."""
import json


def place_continuations_in_appendix(presentation, result):
    """Move whole detail pages without selecting new topics or changing copy.

    Only an existing deep-dive role with a retained overview of the same theme
    is eligible. A body-only limit authorizes appendix placement; total-deck
    limits cannot be satisfied by relabeling pages. Unresolved excess remains
    visible to the normal requirement check.
    """
    requirements = result.profile.report_requirements
    plan = result.presentation_plan
    if not requirements or not plan:
        return
    from .slide_budgets import resolved_limits
    limits = resolved_limits(requirements, scope='body')
    if not limits:
        return
    slides = list(presentation.slides)
    body_count = sum(s.element.cSld.get('name') != 'ada:appendix' for s in slides)
    if body_count <= min(limits):
        return
    overview_themes = {s.theme_id for s in plan.slides
                       if s.slide_type == 'analysis' and s.slide_role == 'overview' and s.theme_id}
    detail_ids = {s.id for s in plan.slides if s.slide_type == 'analysis'
                  and s.slide_role == 'deep_dive' and s.theme_id in overview_themes}
    pages = {n for record in result.presentation_export_trace if record.get('planned_slide_id') in detail_ids
             for n in record['slide_numbers']}
    movable = [i for i, s in enumerate(slides, 1)
               if i in pages and s.element.cSld.get('name') != 'ada:appendix']
    if not movable:
        return
    # All eligible continuations keep source order; no importance ranking is
    # performed by Python. Their theme overviews and closing remain in the body.
    for number in movable:
        slide = slides[number - 1]
        slide.element.cSld.set('name', 'ada:appendix')
        slide.notes_slide.notes_text_frame.text += '\n\nADA_BODY_BUDGET_PLACEMENT_V1\n' + json.dumps({
            'reason': 'Detailed continuation moved to appendix under the explicit body-only slide limit.',
            'original_slide_number': number, 'body_limit': min(limits)}, ensure_ascii=False)
    retained = [i for i in range(1, len(slides) + 1) if i not in movable]
    insertion = next((j for j, i in enumerate(retained)
                      if slides[i - 1].element.cSld.get('name') == 'ada:appendix'), len(retained) - 1)
    order = retained[:insertion] + movable + retained[insertion:]
    identifiers = list(presentation.slides._sldIdLst)
    for element in identifiers:
        presentation.slides._sldIdLst.remove(element)
    for number in order:
        presentation.slides._sldIdLst.append(identifiers[number - 1])
    from .presentation_export_trace import rebase_trace
    rebase_trace(presentation, result, {old: new for new, old in enumerate(order, 1)})
