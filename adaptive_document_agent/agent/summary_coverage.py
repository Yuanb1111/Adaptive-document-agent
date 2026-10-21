"""Bind independently selected central meanings to actual visible source-owned copy."""
from pydantic import BaseModel, ConfigDict, Field
from adaptive_document_agent.services.introduction_audience import required_meanings


class MeaningCoverage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    meaning_index: int = Field(ge=0)
    covered: bool
    paragraph_ids: list[str] = Field(default_factory=list, max_length=256, description=
        'For covered=true, select exact paragraph_id values from this part\'s bound_visible_paragraphs. '
        'Python binds their current visible text. Never cite a source quotation as a visible paragraph.')
    summary_quote: str = Field(default='', max_length=80000, description=
        'Legacy visible-copy quotation. Prefer paragraph_ids and leave this empty; '
        'never copy the source-language quotation when the visible paragraph uses another language.')
    reason: str = Field(min_length=1, max_length=600)


def coverage_errors(verdict, meanings, pages):
    from adaptive_document_agent.services.introduction_audience import coverage_errors as errors
    return errors(verdict.model_dump(), meanings, pages)


def validate_coverage_target(response, review, pages):
    from .compact_summary_review import ReviewTargetError
    meanings = required_meanings(review)
    protocol = []
    for verdict in response.parts:
        failures = coverage_errors(verdict, meanings[verdict.part_id], pages)
        protocol.extend(verdict.part_id + ': ' + error for error in failures
                        if not error.startswith('Missing central meaning:'))
    if protocol:
        raise ReviewTargetError('; '.join(protocol) +
                '. Repair only the review response against the SAME visible copy. Quote literal bound '
                'text by choosing paragraph_ids from this part\'s bound_visible_paragraphs; if the required meaning exists only in another part\'s paragraph, return '
                'covered=false and explain the missing source binding. Do not rewrite the introduction.')
