"""A source review's correct arithmetic cannot replace the audience's predicate."""
import json
from concurrent.futures import CancelledError

import pytest

from adaptive_document_agent.agent.brief_claim_direction import (
    BriefClaimDirectionReview, direction_errors, review_claim_directions,
)
from adaptive_document_agent.agent.brief_meaning_review import (
    BriefMeaningReview, comparison_errors, meaning_validator,
)
from adaptive_document_agent.models.executive_brief import BriefQuote, ExecutiveBrief, ExecutiveBriefItem
from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)
from adaptive_document_agent.services.llm.base import LLMResponse
from tests.test_executive_brief import result_for


def observed_loss(*, wrong_label=False, wrong_body=True):
    source = 'Adjusted net loss was 39,898 in FY2022 and 81,817 in FY2023 (RMB thousand).'
    label = 'Adjusted loss narrows' if wrong_label else 'Adjusted loss widens'
    text = ('Adjusted net loss (non-IFRS) ' + ('narrowed' if wrong_body else 'widened')
            + ' to RMB81,817 thousand in FY2023 from RMB39,898 thousand in FY2022.')
    item = ExecutiveBriefItem(label=label, text=text, evidence=[BriefQuote(page=1, text=source)])
    verdict = dict(index=0, accepted=True, reason='The source endpoints increase in magnitude.',
        numeric_comparison=True, comparisons=[dict(claim=claim, start_value='39,898',
        end_value='81,817', direction='increase', absolute_magnitude=True,
        start_context=source, end_context=source,
        start_duration_months=12, end_duration_months=12) for claim in (label, text)])
    source_review = BriefMeaningReview(items=[verdict])
    audience_review = BriefClaimDirectionReview(items=[dict(index=0, comparisons=[
        dict(comparison_index=i, claim=claim, predicate=predicate, direction=direction,
             absolute_magnitude=True, reason='The predicate states the direction of loss magnitude.')
        for i, claim, predicate, direction in [
            (0, label, 'narrows' if wrong_label else 'widens', 'decrease' if wrong_label else 'increase'),
            (1, text, 'narrowed' if wrong_body else 'widened', 'decrease' if wrong_body else 'increase')]],
        omitted_directional_claims=[])])
    return ExecutiveBrief(items=[item]), result_for([source]), source_review, audience_review


class Gateway:
    def __init__(self, source, audience):
        self.source = source
        self.audience = audience
        self.calls = []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append((messages, schema, kwargs))
        assert kwargs['stage'] == 'report' and kwargs['allow_repair'] is False
        if schema is BriefMeaningReview:
            return self.source
        assert schema is BriefClaimDirectionReview
        return self.audience


@pytest.mark.parametrize(('wrong_label', 'wrong_body'), [(False, True), (True, False), (True, True)])
def test_observed_narrowing_cannot_borrow_increase_from_the_source_arithmetic(wrong_label, wrong_body):
    brief, result, source, audience = observed_loss(wrong_label=wrong_label, wrong_body=wrong_body)
    assert all(not comparison_errors(c, brief.items[0]) for c in source.items[0].comparisons)
    gateway = Gateway(source, audience)
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    assert any('Audience predicate direction contradicts' in e and 'decrease, not increase' in e for e in errors[0])
    # A genuine predicate contradiction goes directly to content repair.
    assert validate(brief) == errors and len(gateway.calls) == 2
    independent_payload = json.loads(gateway.calls[1][0][1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert set(independent_payload[0]) == {'index', 'label', 'text', 'comparisons'}
    assert all(set(c) == {'comparison_index', 'claim'} for c in independent_payload[0]['comparisons'])
    assert result.stage_details_ms['executive_brief_direction_review'] >= 0
    audit = json.loads(next(w.message for w in result.validation_warnings if w.code == 'executive_brief_direction_audit'))
    assert audit['errors']['0'] == errors[0]


def test_corrected_copy_gets_fresh_source_and_predicate_reviews_then_memoizes():
    wrong, result, source, audience = observed_loss()
    gateway = Gateway(source, audience)
    validate = meaning_validator(gateway, result=result)
    assert validate(wrong)
    correct, _, gateway.source, gateway.audience = observed_loss(wrong_body=False)
    assert validate(correct) == {}
    assert validate(correct) == {} and len(gateway.calls) == 4


@pytest.mark.parametrize('mutation', ['claim', 'predicate', 'basis', 'direction', 'missing', 'duplicate', 'omitted_label', 'not_asserted'])
def test_independent_review_is_bound_and_fail_closed(mutation):
    brief, result, source, audience = observed_loss(wrong_body=False)
    row = audience.items[0]
    if mutation == 'claim':
        row.comparisons[1].claim = 'A paraphrased claim'
    elif mutation == 'predicate':
        row.comparisons[1].predicate = 'grew'
    elif mutation == 'basis':
        row.comparisons[1].absolute_magnitude = False
    elif mutation == 'direction':
        row.comparisons[1].direction = 'uncertain'
    elif mutation == 'missing':
        row.comparisons.pop()
    elif mutation == 'duplicate':
        row.comparisons[1].comparison_index = 0
    elif mutation == 'omitted_label':
        row.omitted_directional_claims = [brief.items[0].label]
    else:
        row.comparisons[1].direction = 'not_asserted'
        row.comparisons[1].predicate = ''
    assert meaning_validator(Gateway(source, audience), result=result)(brief)


@pytest.mark.parametrize('error', [CancelledError('stop'), PrivacyViolationError('local only'), LLMTransportError('offline')])
def test_cancellation_privacy_and_transport_never_certify_the_pending_item(error):
    brief, result, source, audience = observed_loss(wrong_body=False)

    class Interrupted(Gateway):
        failing = True

        def generate_structured(self, messages, schema, **kwargs):
            if schema is BriefClaimDirectionReview and self.failing:
                self.calls.append((messages, schema, kwargs))
                raise error
            return super().generate_structured(messages, schema, **kwargs)

    gateway = Interrupted(source, audience)
    validate = meaning_validator(gateway, result=result)
    with pytest.raises(type(error)):
        validate(brief)
    gateway.failing = False
    assert validate(brief) == {}
    assert len(gateway.calls) == 4


def test_format_failure_has_only_one_retry_and_cannot_accept_source_only():
    brief, result, source, audience = observed_loss(wrong_body=False)

    class Malformed(Gateway):
        def generate_structured(self, messages, schema, **kwargs):
            if schema is BriefClaimDirectionReview:
                self.calls.append((messages, schema, kwargs))
                raise LLMStructuredOutputError('invalid JSON', response=LLMResponse(text='broken'))
            return super().generate_structured(messages, schema, **kwargs)

    gateway = Malformed(source, audience)
    validate = meaning_validator(gateway, result=result)
    assert 'unavailable' in str(validate(brief))
    assert 'unavailable' in str(validate(brief)) and len(gateway.calls) == 3
    assert gateway.calls[1][0][:2] == gateway.calls[2][0][:2]


def test_source_rejection_is_never_rescued_by_an_independent_predicate_review():
    brief, result, source, audience = observed_loss(wrong_body=False)
    source.items[0].accepted = False
    gateway = Gateway(source, audience)
    assert meaning_validator(gateway, result=result)(brief)
    assert len(gateway.calls) == 1


def test_source_reviewer_cannot_bypass_direction_review_by_declaring_no_comparisons():
    brief, result, source, audience = observed_loss()
    source.items[0].numeric_comparison = False
    source.items[0].comparisons = []
    audience.items[0].comparisons = []
    audience.items[0].omitted_directional_claims = [brief.items[0].text]
    gateway = Gateway(source, audience)
    assert 'lacks its own source-bound comparison' in str(meaning_validator(gateway, result=result)(brief))
    assert len(gateway.calls) == 4


def test_separately_reported_facts_can_have_no_direction_but_still_receive_independent_review():
    text = 'Revenue was USD12 million in FY2023 and USD18 million in FY2024.'
    item = ExecutiveBriefItem(label='Reported revenue', text=text, evidence=[BriefQuote(page=1, text=text)])
    source = BriefMeaningReview(items=[dict(index=0, accepted=True, reason='The dated facts match.',
        numeric_comparison=False, comparisons=[])])
    audience = BriefClaimDirectionReview(items=[dict(index=0, comparisons=[], omitted_directional_claims=[])])
    gateway = Gateway(source, audience)
    validate = meaning_validator(gateway, result=result_for([text]))
    assert validate(ExecutiveBrief(items=[item])) == {}
    assert validate(ExecutiveBrief(items=[item])) == {} and len(gateway.calls) == 2


@pytest.mark.parametrize(('claim', 'start', 'end', 'source_direction', 'predicate', 'asserted', 'magnitude'), [
    ('Temperature fell from -20 to -10.', '-20', '-10', 'increase', 'fell', 'decrease', False),
    ('The deficit contracted from 20 to 30.', '-20', '-30', 'increase', 'contracted', 'decrease', True),
    ('The shortfall widened from 30 to 20.', '-30', '-20', 'decrease', 'widened', 'increase', True),
    ('产量从20下降至30。', '20', '30', 'increase', '下降', 'decrease', False),
])
def test_predicate_cross_check_is_independent_of_metric_language_and_signed_scale(
        claim, start, end, source_direction, predicate, asserted, magnitude):
    source = f'The reported endpoints were {start} and {end}.'
    item = ExecutiveBriefItem(label='Comparison', text=claim, evidence=[BriefQuote(page=1, text=source)])
    brief = ExecutiveBrief(items=[item])
    review = BriefMeaningReview(items=[dict(index=0, accepted=True, reason='Endpoints support this direction.',
        numeric_comparison=True, comparisons=[dict(claim=claim, start_value=start, end_value=end,
            direction=source_direction, absolute_magnitude=magnitude, start_context=source, end_context=source)])])
    assert comparison_errors(review.items[0].comparisons[0], item) == []
    audience = BriefClaimDirectionReview(items=[dict(index=0, comparisons=[dict(comparison_index=0,
        claim=claim, predicate=predicate, direction=asserted, absolute_magnitude=magnitude,
        reason='The literal predicate, independently read from audience text.')])])
    assert 'Audience predicate direction contradicts' in str(meaning_validator(
        Gateway(review, audience), result=result_for([source]))(brief))


def test_reported_delta_cannot_relabel_a_decrease_as_the_sources_increase():
    source = 'Deposits increased by USD12 million.'
    claim = 'Deposits decreased by USD12 million.'
    item = ExecutiveBriefItem(label='Deposits', text=claim, evidence=[BriefQuote(page=1, text=source)])
    review = BriefMeaningReview(items=[dict(index=0, accepted=True, reason='The exact delta is supported.',
        numeric_comparison=True, comparisons=[dict(claim=claim, comparison_kind='reported_delta',
            direction='increase', delta_value='USD12 million', delta_context=source,
            delta_quote=source, source_direction='increase')])])
    assert comparison_errors(review.items[0].comparisons[0], item) == []
    audience = BriefClaimDirectionReview(items=[dict(index=0, comparisons=[dict(comparison_index=0,
        claim=claim, predicate='decreased', direction='decrease', absolute_magnitude=False,
        reason='The audience predicate explicitly says decreased.')])])
    assert 'Audience predicate direction contradicts' in str(meaning_validator(
        Gateway(review, audience), result=result_for([source]))(ExecutiveBrief(items=[item])))
