"""Correct the independent source review's format without rewriting its draft."""
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .presentation_budget_output import complete_budget_output
from .structured_output_correction import schema_feedback, format_correction_messages


class SourceReviewContractError(ValueError):
    """An exhausted reviewer format correction cannot borrow a writer retry."""


def review_output(gateway, messages, schema, entry, checks, budget, *, token_limits):
    for _ in range(2):
        try:
            review = complete_budget_output(gateway, messages, schema, entry,
                audit_key='review_output_attempts', token_limits=token_limits, stage='report')
        except LLMStructuredOutputError as exc:
            feedback = schema_feedback(exc, schema)
        else:
            verdicts = {v.section_id: v for v in review.verdicts}
            if len(verdicts) == len(review.verdicts) and set(verdicts) == set(checks):
                return review  # Semantic rejections remain the caller's responsibility.
            feedback = dict(validation_error='Return exactly one verdict per supplied section_id.',
                            expected_section_ids=list(checks), rejected_review=review.model_dump(mode='json'))
        entry.setdefault('review_format_failures', []).append(feedback)
        if budget['review_format']:
            raise SourceReviewContractError('Independent source review format correction exhausted.')
        budget['review_format'] += 1
        messages = [*messages, *format_correction_messages(feedback)]
