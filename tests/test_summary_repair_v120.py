"""Length boundaries, stage-specific repairs, and repeated rejected copy."""
import json

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.compact_summary import (
    CompactSummaryDraft, CompactSummaryReview, CompactSummaryItem, compact_input,
    expand_compact, generate_compact_summary,
)
from adaptive_document_agent.agent.summary_theme_layout import pack_theme_pages
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from tests.test_compact_summary_v111 import fixture, Reviewer


def test_601_character_complete_paragraph_is_preserved_and_checked_for_real_capacity():
    result, review, draft = fixture(1)
    text = ('Scheduling requires staff training before service delivery. ' * 9
            + 'Staff training must precede both scheduling and any delivery.')
    draft['pages'][0]['items'][0]['text'] = text
    _, catalog = compact_input(review)
    pages = pack_theme_pages(expand_compact(CompactSummaryDraft.model_validate(draft), catalog, review))
    assert pages[0].items[0].text == text
    assert len(pages[0].items[0].text) == 601
    with pytest.raises(ValidationError):
        CompactSummaryItem(label='Scheduling', text='a' * 6001, fact_ids=['f0'])


def test_reason_above_160_characters_does_not_discard_valid_verdicts():
    result, review, draft = fixture(10)
    class Client(Reviewer):
        def generate_structured(self, messages, schema, **kwargs):
            response = super().generate_structured(messages, schema, **kwargs)
            if schema is CompactSummaryReview:
                data = response.model_dump()
                for part in data['parts']:
                    part['reason'] = 'The complete paragraph preserves the stated staff training prerequisite. ' * 5
                return schema.model_validate(data)
            return response
    client = Client(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert company.summary_pages
    assert client.calls == ['CompactSummaryDraft', 'CompactSummaryReview']


@pytest.mark.parametrize('persistent', [False, True])
def test_review_format_retry_keeps_same_source_and_pages_without_rewriting(persistent):
    result, review, draft = fixture(10)
    class Client(Reviewer):
        review_calls = 0
        source_request = None
        def generate_structured(self, messages, schema, **kwargs):
            if schema is CompactSummaryReview:
                self.review_calls += 1
                if self.review_calls == 1:
                    self.source_request = messages[-1]
                else:
                    assert messages[1] == self.source_request
                    assert 'opening_accepted' in messages[-2]['content']
                    assert 'SAME pages' in messages[-1]['content']
                if persistent or self.review_calls == 1:
                    self.calls.append(schema.__name__)
                    raw = json.dumps({'parts': [], 'opening_reason': 'Verdict omitted.'})
                    try:
                        schema.model_validate_json(raw)
                    except ValidationError as exc:
                        raise LLMStructuredOutputError('Invalid reviewer schema', response=LLMResponse(text=raw)) from exc
                # Existing fixture reviewer reads the evidence payload last.
                return super().generate_structured(messages[:2], schema, **kwargs)
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(draft)
    company = CompanyProfile(summary_review=review)
    if persistent:
        with pytest.raises(ValueError, match='review protocol failed'):
            generate_compact_summary(client, result, review, company)
        assert not company.summary_pages
    else:
        generate_compact_summary(client, result, review, company)
        assert company.summary_pages
    assert client.calls == ['CompactSummaryDraft', 'CompactSummaryReview', 'CompactSummaryReview']
    assert len(review.plan_audits) == 1
    attempts = review.plan_audits[0]['compact_review_attempts']
    assert len(attempts) == 2 and 'opening_accepted' in attempts[0]['validation_detail']


def test_unchanged_numeric_repair_is_detected_before_another_review():
    result, review, draft = fixture(10)
    draft['pages'][0]['items'][0]['text'] = 'Teams generated RMB999 million revenue.'
    client = Reviewer(draft)
    with pytest.raises(ValueError, match='repeated the rejected draft'):
        generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.calls == ['CompactSummaryDraft'] * 2
    assert review.plan_audits[-1]['repeated_draft']


def test_numeric_repair_has_exact_previous_copy_errors_and_succeeds_after_correction():
    result, review, draft = fixture(10)
    class Client(Reviewer):
        attempts = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema is CompactSummaryDraft:
                self.attempts += 1
                if self.attempts == 2:
                    assert 'RMB999 million' in messages[-2]['content']
                    assert 'unsupported numeric claims' in messages[-2]['content']
            response = super().generate_structured(messages, schema, **kwargs)
            if schema is CompactSummaryDraft and self.attempts == 1:
                response.pages[0].items[0].text = 'Teams generated RMB999 million revenue.'
            return response
    client = Client(draft)
    generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.calls == ['CompactSummaryDraft', 'CompactSummaryDraft', 'CompactSummaryReview']
