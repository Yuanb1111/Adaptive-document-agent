"""Bind explicit numeric controls without asking a model to reinterpret them."""
from adaptive_document_agent.models.customization import PresentationBudget, ReportRequirement, ReportRequirements


def budget_request(instructions: str, budget: PresentationBudget) -> str:
    scope = 'body' if budget.slide_scope == 'body' else 'entire PPT file'
    appendix = ('Appendices are counted separately and excluded from both body limits.' if budget.slide_scope == 'body'
                else 'All appendices, Data Index, conclusion and closing count toward the total file limit.')
    return (instructions.strip() + '\n' if instructions.strip() else '') + (
        f'The presentation {scope} must contain at most {budget.body_slides} physical slides, '
        'including cover, contents, introduction and closing. '
        f'The introduction must contain at most {min(budget.body_slides, budget.introduction_slides)} physical slides. '
        f'The data/chart analysis must contain at most {budget.analysis_slides} physical slides. '
        'Aim for five to ten informative chart pages when the source supports them. ' + appendix)


def apply_presentation_budget(requirements, instructions: str, budget: PresentationBudget):
    """Retain free-text requirements and their errors; explicit budgets remain enforced."""
    bound = requirements.model_copy(deep=True) if requirements else ReportRequirements()
    bound.original_request = budget_request(instructions, budget)
    for section, limit, quote in [
        ('report', budget.body_slides, budget_request('',budget).split('. ')[0] + '.'),
        ('introduction', min(budget.body_slides, budget.introduction_slides),
         f'The introduction must contain at most {min(budget.body_slides, budget.introduction_slides)} physical slides.'),
        ('analysis', budget.analysis_slides, f'The data/chart analysis must contain at most {budget.analysis_slides} physical slides.')]:
        identifier = 'presentation_control_' + section
        while any(r.id == identifier for r in bound.items):
            identifier += '_'
        bound.items.append(ReportRequirement(id=identifier, request_quote=quote,
            description=f'Maximum {section} {budget.slide_scope} slides: {limit}.',
            kind='slide_limit', resolution='resolved', max_slides=limit,
            slide_section=section, slide_scope=budget.slide_scope))
    return ReportRequirements.model_validate(bound.model_dump())
