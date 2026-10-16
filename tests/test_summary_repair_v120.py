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
    assert client.calls == ['CompactSummaryDraft', 'SummarySynthesisRevision', 'SummarySynthesisRevision']
    assert review.plan_audits[-1]['revision_failed']


def test_new_semantic_omissions_get_one_additive_correction_after_prior_failures_clear():
    result, review, draft = fixture(10)
    class Client(Reviewer):
        reviews = 0
        repairs = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'SummarySynthesisRevision':
                self.calls.append(schema.__name__)
                self.repairs += 1
                if self.repairs == 1:
                    item = dict(draft['pages'][0]['items'][0])
                    item['text'] += ' Delivery depends on staff training.'
                    return schema(replacements=[dict(item_id='g0_i0', replacement=item)])
                assert schema.model_json_schema()['properties']['replacements']['maxItems'] == 0
                return schema(additions=[dict(group_id='g0', item=dict(label='Training conditions',
                    text='Scheduling and service delivery require completed staff training for the affected teams.',
                    fact_ids=['f1', 'f2']))])
            response = super().generate_structured(messages, schema, **kwargs)
            if schema is CompactSummaryReview:
                self.reviews += 1
                rejected = {'part-0'} if self.reviews == 1 else {'part-1', 'part-2'} if self.reviews == 2 else set()
                response.parts = [p.model_copy(update={'accepted': p.part_id not in rejected,
                    'reason': 'Material condition missing.' if p.part_id in rejected else 'Supported.'})
                    for p in response.parts]
            return response
    client = Client(draft)
    company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert company.summary_pages
    assert client.repairs == 2 and client.reviews == 3
    assert review.plan_audits[-1]['content_revision_policy'] == 'additive_meaning_regression'


@pytest.mark.parametrize('progress', [True, False])
def test_source_repair_gets_one_extra_attempt_only_for_strictly_fewer_failures(progress):
    from copy import deepcopy
    result, review, valid = fixture(20)
    invalid=deepcopy(valid)
    invalid['pages'][0]['items'][0]['text']='Unsupported amount RMB999 million.'
    invalid['pages'][1]['items'][0]['text']='Unsupported amount RMB888 million.'
    class Client(Reviewer):
        repairs=0
        def generate_structured(self,messages,schema,**kwargs):
            if schema.__name__=='SummarySynthesisRevision':
                self.repairs+=1
                self.calls.append(schema.__name__)
                index=0 if self.repairs==1 else 1
                item=deepcopy(valid['pages'][index]['items'][0])
                if not progress: item['text']='Another unsupported amount RMB777 million.'
                return schema(replacements=[dict(item_id=f'g{index}_i0',replacement=item)])
            return super().generate_structured(messages,schema,**kwargs)
    client=Client(invalid)
    company=CompanyProfile(summary_review=review)
    if progress:
        assert generate_compact_summary(client,result,review,company).summary_pages
        assert client.repairs==2
    else:
        with pytest.raises(ValueError): generate_compact_summary(client,result,review,company)
        assert client.repairs==2  # One bounded correction for a non-progress proposal.


def test_numeric_repair_has_exact_previous_copy_errors_and_succeeds_after_correction():
    result, review, draft = fixture(10)
    class Client(Reviewer):
        attempts = 0
        def generate_structured(self, messages, schema, **kwargs):
            if issubclass(schema, CompactSummaryDraft) or schema.__name__ == 'SummarySynthesisRevision':
                self.attempts += 1
                if self.attempts == 2:
                    assert 'RMB999 million' in messages[-1]['content']
                    assert 'unsupported numeric claims' in messages[-1]['content']
            response = super().generate_structured(messages, schema, **kwargs)
            if issubclass(schema, CompactSummaryDraft) and self.attempts == 1:
                response.pages[0].items[0].text = 'Teams generated RMB999 million revenue.'
            return response
    client = Client(draft)
    generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
    assert client.calls == ['CompactSummaryDraft', 'SummarySynthesisRevision', 'CompactSummaryReview']
