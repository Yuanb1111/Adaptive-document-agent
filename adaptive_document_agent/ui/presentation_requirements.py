"""Carry visible presentation settings through the ordinary analysis request."""


def with_slide_limits(instructions: str, body_limit: int, introduction_limit: int) -> str:
    """Append user-configurable budgets before request hashing or orchestration."""
    from adaptive_document_agent.models.customization import PresentationBudget
    from adaptive_document_agent.services.presentation_requirements import budget_request
    return budget_request(instructions, PresentationBudget(body_slides=body_limit,
        introduction_slides=introduction_limit))
