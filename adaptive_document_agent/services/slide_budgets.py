"""Keep user section limits distinct and verify actual exported page counts."""


def resolved_limits(requirements, *, section='report', scope=None):
    return [r.max_slides for r in requirements.items
            if r.kind == 'slide_limit' and r.resolution == 'resolved'
            and r.slide_section == section and (scope is None or r.slide_scope == scope)
            and r.max_slides is not None] if requirements else []


def introduction_limit(requirements):
    section = resolved_limits(requirements, section='introduction')
    report = resolved_limits(requirements)
    if section:
        return min(5, min(section), min(report) if report else 5)
    return min(5, max(1, min(report) // 3)) if report else None


def exported_slide_numbers(presentation, result, requirement):
    numbers = set(range(1, len(presentation.slides) + 1))
    if requirement.slide_section == 'introduction':
        from .summary_export import _PREFIX
        numbers = {n for n, slide in enumerate(presentation.slides, 1)
                   if any((properties := shape.element.xpath('.//p:cNvPr'))
                          and properties[0].get('descr', '').startswith(_PREFIX)
                          for shape in slide.shapes)}
        if not numbers and result.presentation_plan:
            ids = {s.id for s in result.presentation_plan.slides if s.slide_type == 'company_overview'}
            numbers = {n for record in result.presentation_export_trace
                       if record.get('planned_slide_id') in ids for n in record['slide_numbers']}
    if requirement.slide_scope == 'body':
        numbers = {n for n in numbers if presentation.slides[n - 1].element.cSld.get('name') != 'ada:appendix'}
    return sorted(numbers)


def require_exported_budgets(presentation, result):
    requirements = result.profile.report_requirements
    errors = []
    for req in requirements.items if requirements else []:
        if req.kind != 'slide_limit' or req.resolution != 'resolved' or req.max_slides is None:
            continue
        count = len(exported_slide_numbers(presentation, result, req))
        if count > req.max_slides:
            errors.append(f'{req.id}: {req.slide_section} {req.slide_scope} has {count} physical slides; '
                          f'user maximum is {req.max_slides}')
    if errors:
        raise ValueError('PowerPoint exceeds the requested slide budget: ' + '; '.join(errors))
