"""Bind explicit numeric controls without asking a model to reinterpret them."""
from adaptive_document_agent.models.customization import PresentationBudget, ReportRequirement, ReportRequirements


def budget_request(instructions: str, budget: PresentationBudget) -> str:
    return (instructions.strip() + '\n' if instructions.strip() else '') + (
        f'The presentation body must contain at most {budget.body_slides} physical slides, '
        'including cover, contents, introduction and closing. '
        f'The introduction body must contain at most {min(budget.body_slides, budget.introduction_slides)} physical slides. '
        'Appendices are counted separately and excluded from both body limits.')


def apply_presentation_budget(requirements, instructions: str, budget: PresentationBudget):
    """Retain free-text requirements and their errors; explicit budgets remain enforced."""
    bound = requirements.model_copy(deep=True) if requirements else ReportRequirements()
    bound.original_request = budget_request(instructions, budget)
    for section, limit, quote in [
        ('report', budget.body_slides, f'The presentation body must contain at most {budget.body_slides} physical slides, '
         'including cover, contents, introduction and closing.'),
        ('introduction', min(budget.body_slides, budget.introduction_slides),
         f'The introduction body must contain at most {min(budget.body_slides, budget.introduction_slides)} physical slides.')]:
        identifier = 'presentation_control_' + section
        while any(r.id == identifier for r in bound.items):
            identifier += '_'
        bound.items.append(ReportRequirement(id=identifier, request_quote=quote,
            description=f'Maximum {section} body slides: {limit}; appendices counted separately.',
            kind='slide_limit', resolution='resolved', max_slides=limit,
            slide_section=section, slide_scope='body'))
    return ReportRequirements.model_validate(bound.model_dump())
