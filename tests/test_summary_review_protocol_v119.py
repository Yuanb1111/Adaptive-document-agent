"""Missing verdicts are protocol failures; retries retain concrete diagnostics."""
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.compact_summary import (
    CompactSummaryDraft, CompactSummaryReview, generate_compact_summary,
)
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_compact_summary_v111 import fixture, Reviewer


def test_opening_verdict_and_reason_are_required_not_silent_defaults():
    with pytest.raises(ValidationError, match='opening_accepted'):
        CompactSummaryReview.model_validate({'parts': [], 'opening_reason': 'No verdict supplied.'})
    with pytest.raises(ValidationError, match='opening_reason'):
        CompactSummaryReview.model_validate({'parts': [], 'opening_accepted': False})


def test_schema_retry_supplies_raw_draft_and_exact_field_failure():
    result, review, draft = fixture(10)
    raw = json.dumps({'pages': [{'title': 'Scheduling', 'items': []}]})
    class Client(Reviewer):
        attempts = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema is CompactSummaryDraft:
                self.attempts += 1
                if self.attempts == 1:
                    try:
                        schema.model_validate_json(raw)
                    except ValidationError as exc:
                        raise LLMStructuredOutputError('Structured response failed schema validation.',
                                                       response=LLMResponse(text=raw)) from exc
                repair = json.loads(messages[-2]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
                assert repair['raw_response'] == raw
                assert 'pages.0.items' in repair['validation_detail']
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert company.summary_pages and client.attempts == 2
    assert review.plan_audits[0]['draft_format_attempts'][0]['raw_response'] == raw


def test_rejected_opening_reason_reaches_editorial_repair():
    result, review, draft = fixture(10)
    class Client(Reviewer):
        attempts = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema is CompactSummaryDraft or schema.__name__ == 'SummarySynthesisRevision':
                self.attempts += 1
                if self.attempts == 2:
                    assert 'Missing actual service scope' in messages[-1]['content']
            value = super().generate_structured(messages, schema, **kwargs)
            if schema is CompactSummaryDraft and self.attempts == 1:
                value.pages[0].items[0].text = 'This page lists teams and the topics described in the document.'
            if schema is CompactSummaryReview and self.attempts == 1:
                value.opening_accepted = False
                value.opening_reason = 'Missing actual service scope'
            return value
    client = Client(draft)
    generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.attempts == 2
