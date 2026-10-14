"""Bind independently selected central meanings to actual visible source-owned copy."""
from pydantic import BaseModel, ConfigDict, Field
from adaptive_document_agent.services.introduction_audience import required_meanings


class MeaningCoverage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    meaning_index: int = Field(ge=0)
    covered: bool
    summary_quote: str = Field(max_length=2000)
    reason: str = Field(min_length=1, max_length=600)


def coverage_errors(verdict, meanings, pages):
    from adaptive_document_agent.services.introduction_audience import coverage_errors as errors
    return errors(verdict.model_dump(), meanings, pages)


def validate_coverage_target(response, review, pages):
    from .compact_summary_review import ReviewTargetError
    meanings = required_meanings(review)
    for verdict in response.parts:
        failures = coverage_errors(verdict, meanings[verdict.part_id], pages)
        protocol = [error for error in failures if not error.startswith('Missing central meaning:')]
        if protocol:
            raise ReviewTargetError(verdict.part_id + ': ' + '; '.join(protocol) +
                '. Repair only the review response against the SAME visible copy. Quote literal bound '
                'text; if the required meaning exists only in another part\'s paragraph, return '
                'covered=false and explain the missing source binding. Do not rewrite the introduction.')
