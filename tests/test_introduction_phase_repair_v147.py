"""A selection rewrite can still use the last bounded round for meaning repair."""
from concurrent.futures import CancelledError
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience import complete_response, select_introduction_audience
from adaptive_document_agent.agent.introduction_audience_review import IntroductionAudienceReview
from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, PrivacyViolationError
from adaptive_document_agent.services.llm.usage import LLMUsage
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_compact_summary_v111 import fixture


class SelectionThenMeaningClient:
    def __init__(self, reading, *, final_acceptance=True, missing_edit=False):
        self.reading = reading
        self.final_acceptance = final_acceptance
        self.missing_edit = missing_edit
        self.calls, self.reviews, self.selections = [], [], []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema.__name__ == 'IntroductionAudienceSelection':
            include_condition = bool(self.selections)
            value = schema(decisions=[dict(part_id=part.id, include=index == 0 or (index == 1 and include_condition),
                reason='Service scope.' if index == 0 else 'Essential delivery condition.' if include_condition and index == 1
                else 'Redundant service context.', required_meanings=[dict(meaning=(
                    'The service schedules appointments.' if index == 0 else
                    'The service uses local and remote channels.'))] if index == 0 or (index == 1 and include_condition)
                else []) for index, part in enumerate(self.reading.parts)])
            self.selections.append(value.model_dump())
            return value
        payload = review_payload(messages)
        if schema.__name__ == 'IntroductionMeaningRevision':
            assert len(self.reviews) == 2
            assert payload['source']['parts'] == self.reviews[1]['source']['parts']
            assert payload['original_meanings'] == [
                dict(meaning_id='meaning-0', part_id='part-0', meaning_index=0,
                     meaning='The service schedules appointments.'),
                dict(meaning_id='meaning-1', part_id='part-1', meaning_index=0,
                     meaning='The service uses local and remote channels.')]
            edits = [dict(meaning_id='meaning-0', required_meanings=[dict(
                meaning='The service schedules appointments.')]), dict(meaning_id='meaning-1', required_meanings=[dict(
                meaning='Local channels support low latency; remote channels serve distant users.')])]
            return schema(edits=edits[1:] if self.missing_edit else edits)
        assert schema is IntroductionAudienceReview
        assert kwargs['max_tokens'] == 32000
        self.reviews.append(deepcopy(payload))
        assert [part['id'] for part in payload['source']['parts']] == ['part-0', 'part-1', 'part-2']
        if len(self.reviews) == 1:
            finding = dict(kind='omitted_part', issue_type='missing_qualification', part_id='part-1',
                source_quote=self.reading.parts[1].source_text, reason='The delivery channel distinction is essential.')
            return review_response(schema, messages, accepted=False, repair_scope='selection',
                findings=[finding], reason=finding['reason'])
        if len(self.reviews) == 3:
            # The preservation baseline is the ENTIRE current rewritten selection,
            # including assertions newly chosen after the first selection review.
            assert payload['meaning_revision_base'] == self.reviews[1]['decisions']
            assert payload['meaning_resolution'] is None
            assert payload['decisions'][0] == self.reviews[1]['decisions'][0]
            assert payload['decisions'][2] == self.reviews[1]['decisions'][2]
            assert [(row['part_id'], row['include'], row['reason']) for row in payload['decisions']] == [
                (row['part_id'], row['include'], row['reason']) for row in self.reviews[1]['decisions']]
            if self.final_acceptance:
                return review_response(schema, messages, accepted=True, reason='Fresh full-source union review accepts the correction.')
        target = next(row for row in payload['current_meanings'] if row['part_id'] == 'part-1')
        finding = dict(kind='meaning', issue_type='missing_qualification', part_id=target['part_id'],
            meaning_id=target['meaning_id'], current_meaning=target['meaning'],
            source_quote=self.reading.parts[1].source_text, reason='The distinguishing channel characteristics need source review.')
        return review_response(schema, messages, accepted=False, repair_scope='meanings',
            findings=[finding], reason=finding['reason'])


def phase_context():
    result, reading, _ = fixture(3)
    reading.parts[0].source_text = 'The service schedules appointments.'
    reading.parts[1].source_text = ('The service uses local and remote channels. Local channels support low latency; '
                                    'remote channels serve distant users.')
    reading.parts[2].source_text = 'A prior service pilot used these same channels.'
    return result, reading


@pytest.mark.parametrize('final_acceptance', [True, False])
def test_selection_rewrite_then_first_meaning_correction_requires_last_independent_review(final_acceptance):
    result, reading = phase_context()
    original = deepcopy(reading.parts)
    client = SelectionThenMeaningClient(reading, final_acceptance=final_acceptance)
    if final_acceptance:
        select_introduction_audience(client, result, reading)
        assert reading.audience_selection['independent_review']['accepted']
        assert reading.audience_part_ids == ['part-0', 'part-1']
        assert len(reading.audience_selection['attempts']) == 3
    else:
        with pytest.raises(ValueError, match='not independently accepted'):
            select_introduction_audience(client, result, reading)
        assert not reading.audience_selection and reading.audience_part_ids is None
        assert len([item for item in reading.plan_audits if 'introduction_audience_attempt' in item]) == 3
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceReview',
        'IntroductionAudienceSelection', 'IntroductionAudienceReview',
        'IntroductionMeaningRevision', 'IntroductionAudienceReview']
    assert client.reviews[0]['meaning_revision_base'] is client.reviews[1]['meaning_revision_base'] is None
    assert reading.parts == original


def test_late_meaning_correction_cannot_omit_an_existing_current_assertion_mapping():
    result, reading = phase_context()
    client = SelectionThenMeaningClient(reading, missing_edit=True)
    with pytest.raises(ValueError, match='every exact original meaning_id once'):
        select_introduction_audience(client, result, reading)
    assert len(client.reviews) == 2 and client.calls[-1] == 'IntroductionMeaningRevision'
    assert not reading.audience_selection and reading.audience_part_ids is None


def output_failure(*, finish='length'):
    return LLMStructuredOutputError('Synthetic capacity exhaustion.', response=LLMResponse(text='partial',
        usage=LLMUsage(provider='mock', model='offline', finish_reason=finish)))


def test_full_source_review_starts_at_supported_capacity_and_retries_identical_context_once():
    calls = []
    expected = IntroductionAudienceReview(accepted=False, reason='Semantic rejection is retained.')
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append((deepcopy(messages), kwargs))
            assert schema is IntroductionAudienceReview and kwargs['allow_repair'] is False
            if len(calls) == 1:
                raise output_failure()
            return expected
    messages = [{'role': 'user', 'content': 'Complete source and current selection.'}]
    assert complete_response(Client(), messages, IntroductionAudienceReview) is expected
    assert [options['max_tokens'] for _, options in calls] == [32000, 40000]
    assert calls[0][0] == calls[1][0] == messages


def test_second_full_source_review_truncation_is_terminal_without_a_third_transport_attempt():
    calls = []
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(kwargs['max_tokens'])
            raise output_failure()
    with pytest.raises(LLMStructuredOutputError):
        complete_response(Client(), [], IntroductionAudienceReview)
    assert calls == [32000, 40000]


@pytest.mark.parametrize('failure', [output_failure(finish='stop'), PrivacyViolationError('Local Only guard'), CancelledError()])
def test_full_source_review_capacity_does_not_retry_nontruncation_or_privacy_failures(failure):
    calls = []
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(kwargs['max_tokens'])
            raise failure
    with pytest.raises(type(failure)) as raised:
        complete_response(Client(), [], IntroductionAudienceReview)
    assert raised.value is failure and calls == [32000]
