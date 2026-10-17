"""Offline protocol recovery for late findings on arbitrary introductory source.

Synthetic author/reviewer responses test orchestration, never real model quality.
"""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_compact_summary_v111 import fixture


def adaptive_recovery_fixture():
    result, reading, _ = fixture(3)
    passages = [
        'The platform schedules appointments only after staff training. '
        'The platform supports staff coordination. Local deployment requires onsite review.',
        'The service serves local customers. Remote access is unavailable.',
        'A prior pilot used the same scheduling workflow.',
    ]
    for part, passage in zip(reading.parts, passages):
        part.source_text = passage
    return result, reading


class SyntheticAdaptiveRecoveryClient:
    """Explicit source-owned changes followed by separate independent verdicts."""

    def __init__(self, reading, outcome='accept'):
        self.reading, self.outcome = reading, outcome
        self.calls, self.reviews, self.resolutions = [], [], []

    @staticmethod
    def late_finding(part_id='part-0', quote='Local deployment requires onsite review.'):
        return dict(kind='included_part', issue_type='new_assertion', part_id=part_id,
            source_quote=quote,
            reason='This newly identified service restriction is essential introductory context.')

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema.__name__ == 'IntroductionAudienceSelection':
            return schema(decisions=[dict(part_id=part.id, include=index < 2,
                reason='Core service scope.' if index < 2 else 'Historical detail remains in source records.',
                required_meanings=[dict(meaning=(
                    'The platform schedules appointments and supports staff coordination.'
                    if index == 0 else 'The service serves local customers.'))] if index < 2 else [])
                for index, part in enumerate(self.reading.parts)])
        payload = review_payload(messages)
        if schema.__name__ == 'IntroductionMeaningRevision':
            return schema(edits=[dict(meaning_id='meaning-0', required_meanings=[
                dict(meaning='The platform schedules appointments.'),
                dict(meaning='The platform supports staff coordination.')]),
                dict(meaning_id='meaning-1', required_meanings=[
                    dict(meaning='The service serves local customers.')])])
        if schema.__name__ == 'IntroductionMeaningResolution':
            self.resolutions.append(deepcopy(payload))
            finding = payload['findings'][0]
            part_id = finding['part_id']
            disposition = dict(finding_id='finding-0', classification=finding['issue_type'],
                action='corrected', source_quote=finding['source_quote'],
                reason='Synthetic targeted correction; fresh independent review is still required.')
            if finding['kind'] == 'meaning':
                disposition['referenced_meaning_ids'] = [finding['meaning_id']]
                return schema(edits=[dict(meaning_id=finding['meaning_id'], required_meanings=[
                    dict(meaning='The platform schedules appointments only after staff training.')])],
                    finding_dispositions=[disposition])
            if self.outcome == 'unchanged_repeat':
                disposition.update(action='outside_selected_scope',
                    reason='Synthetic author proposes leaving this independent assertion outside the introduction.')
                return schema(finding_dispositions=[disposition])
            return schema(additions=[dict(part_id=part_id, required_meanings=[
                dict(meaning=finding['source_quote'])])], finding_dispositions=[disposition])
        assert schema.__name__ == 'IntroductionAudienceReview'
        self.reviews.append(deepcopy(payload))
        round_number = len(self.reviews)
        if round_number <= 2:
            row = payload['current_meanings'][0]
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='Split independent assertions.' if round_number == 1 else 'Retain the necessary training condition.',
                findings=[dict(kind='meaning',
                    issue_type='atomicity' if round_number == 1 else 'missing_qualification',
                    part_id=row['part_id'], meaning_id=row['meaning_id'], current_meaning=row['meaning'],
                    source_quote='The platform schedules appointments only after staff training.',
                    reason='Independent assertions need splitting.' if round_number == 1 else 'Training is necessary.')])
        if round_number == 3 or self.outcome == 'wrong_owner':
            finding = self.late_finding()
            if self.outcome == 'unspecified':
                finding['issue_type'] = 'unspecified'
            elif self.outcome == 'wrong_owner':
                finding['source_quote'] = self.reading.parts[1].source_text
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='A fresh review finds another essential assertion.', findings=[finding])
        if self.outcome == 'unavailable':
            raise LLMResponseError('Synthetic final reviewer unavailable; never auto-approve.')
        if self.outcome == 'stale':
            return schema(accepted=True, reason='Synthetic stale acceptance must fail binding.',
                selection_digest=self.reviews[1]['current_selection_digest'])
        if self.outcome in {'reject', 'unchanged_repeat', 'paraphrased_repeat'}:
            finding = self.late_finding()
            if self.outcome == 'paraphrased_repeat':
                finding.update(source_quote='Local  deployment\nrequires onsite review.',
                    reason='Different wording of the same rejected finding is not progress.')
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='Independent rejection persists.', findings=[finding])
        if round_number == 4 and self.outcome in {'two_late_rounds', 'exhausted'}:
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='A second fresh review discovers a different essential restriction.',
                findings=[self.late_finding('part-1', 'Remote access is unavailable.')])
        if self.outcome == 'exhausted':
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='Even a novel bound rejection cannot exceed the review budget.',
                findings=[self.late_finding(quote='The platform supports staff coordination.')])
        return review_response(schema, messages, accepted=True,
            reason='A fresh independent reviewer accepts the full current source-owned union.')


def assert_source_preserved(reading, original_parts, decisions):
    assert reading.parts == original_parts
    sources = {part.id: part.source_text for part in original_parts}
    for decision in decisions:
        for meaning in decision['required_meanings']:
            assert meaning['source_quote'] == sources[decision['part_id']]


@pytest.mark.parametrize('outcome,review_count', [('accept', 4), ('two_late_rounds', 5)])
def test_late_source_owned_findings_are_repaired_then_independently_accepted(outcome, review_count):
    result, reading = adaptive_recovery_fixture()
    original_parts = deepcopy(reading.parts)
    client = SyntheticAdaptiveRecoveryClient(reading, outcome)

    select_introduction_audience(client, result, reading)

    assert len(client.reviews) == review_count
    assert len(client.resolutions) == review_count - 2
    assert reading.audience_selection['independent_review']['accepted'] is True
    assert reading.audience_part_ids == ['part-0', 'part-1']
    decisions = reading.audience_selection['decisions']
    before_late_recovery = client.reviews[2]['decisions']
    assert decisions[2] == before_late_recovery[2]
    assert decisions[0]['required_meanings'][:2] == before_late_recovery[0]['required_meanings']
    assert decisions[1]['required_meanings'][:1] == before_late_recovery[1]['required_meanings']
    assert [decision['reason'] for decision in decisions] == [
        decision['reason'] for decision in before_late_recovery]
    assert decisions[0]['required_meanings'][-1]['meaning'] == 'Local deployment requires onsite review.'
    if outcome == 'two_late_rounds':
        assert decisions[1]['required_meanings'][-1]['meaning'] == 'Remote access is unavailable.'
        latest_resolution = client.reviews[-1]['meaning_resolution']
        assert latest_resolution['decisions_before'] == client.reviews[-2]['decisions']
        assert latest_resolution['decisions_before'][0]['required_meanings'][-1]['meaning'] == (
            'Local deployment requires onsite review.')
    for review in client.reviews[2:]:
        assert review['meaning_resolution']['semantic_approval'] is False
    assert_source_preserved(reading, original_parts, decisions)


@pytest.mark.parametrize('outcome,review_count,resolution_count', [
    ('reject', 4, 2), ('unavailable', 4, 2), ('stale', 5, 2),
    ('wrong_owner', 4, 1), ('unspecified', 3, 1), ('exhausted', 5, 3),
])
def test_late_recovery_never_auto_accepts_or_uses_unbound_findings(outcome, review_count, resolution_count):
    result, reading = adaptive_recovery_fixture()
    original_parts = deepcopy(reading.parts)
    client = SyntheticAdaptiveRecoveryClient(reading, outcome)

    with pytest.raises((ValueError, LLMResponseError)):
        select_introduction_audience(client, result, reading)

    assert len(client.reviews) == review_count
    assert len(client.resolutions) == resolution_count
    assert reading.audience_part_ids is None and not reading.audience_selection
    assert_source_preserved(reading, original_parts, client.reviews[-1]['decisions'])
    records = [audit['introduction_audience_review'] for audit in reading.plan_audits
        if 'introduction_audience_review' in audit]
    if outcome in {'stale', 'wrong_owner'}:
        assert sum(record['re_review'] for record in records) == 1
        assert records[-1]['status'] == 'invalid_binding'
        assert records[-2]['round'] == records[-1]['round']
    if outcome == 'exhausted':
        budgets = [audit['introduction_recovery_budget'] for audit in reading.plan_audits
            if 'introduction_recovery_budget' in audit]
        assert budgets[-1]['reason'] == 'semantic_review_budget_exhausted'
        assert budgets[-1]['repair_allowed'] is False


class SyntheticLateOmissionClient(SyntheticAdaptiveRecoveryClient):
    """Discover an omitted part after the standard two source-owned corrections."""

    def __init__(self, reading, mixed):
        super().__init__(reading)
        self.mixed, self.addition_requests = mixed, []

    def generate_structured(self, messages, schema, **kwargs):
        if schema.__name__ == 'IntroductionAudienceSelectionAddition':
            self.calls.append(schema.__name__)
            payload = review_payload(messages)
            self.addition_requests.append(deepcopy(payload))
            assert payload['allowed_part_ids'] == ['part-2']
            return schema(decisions=[dict(part_id='part-2', include=True,
                reason='The maintenance limitation is essential introductory context.',
                required_meanings=[dict(meaning=self.reading.parts[2].source_text)])])
        if schema.__name__ == 'IntroductionMeaningResolution' and len(self.reviews) == 3:
            assert self.mixed
            self.calls.append(schema.__name__)
            payload = review_payload(messages)
            self.resolutions.append(deepcopy(payload))
            assert [finding['kind'] for finding in payload['findings']] == ['included_part', 'omitted_part']
            return schema(additions=[dict(part_id='part-0', required_meanings=[
                dict(meaning='Local deployment requires onsite review.')])],
                inclusions=[dict(part_id='part-2', include=True,
                    reason='The maintenance limitation is essential introductory context.',
                    required_meanings=[dict(meaning=self.reading.parts[2].source_text)])],
                finding_dispositions=[dict(finding_id=finding['finding_id'],
                    classification='new_assertion', action='corrected',
                    source_quote=finding['source_quote'],
                    reason='A source-owned addition repairs this exact newly identified assertion.')
                    for finding in payload['findings']])
        if schema.__name__ == 'IntroductionAudienceReview' and len(self.reviews) == 2:
            self.calls.append(schema.__name__)
            payload = review_payload(messages)
            self.reviews.append(deepcopy(payload))
            omission = dict(kind='omitted_part', issue_type='new_assertion', part_id='part-2',
                source_quote=self.reading.parts[2].source_text,
                reason='The maintenance limitation is essential to understanding service availability.')
            return review_response(schema, messages, accepted=False, repair_scope='selection',
                reason='A fresh review discovers essential source omissions.',
                findings=([self.late_finding()] if self.mixed else []) + [omission])
        return super().generate_structured(messages, schema, **kwargs)


@pytest.mark.parametrize('mixed', [False, True])
def test_late_omission_and_mixed_findings_receive_targeted_repairs_before_fresh_acceptance(mixed):
    result, reading = adaptive_recovery_fixture()
    reading.parts[2].source_text = 'Service interruption can occur during maintenance windows.'
    original_parts = deepcopy(reading.parts)
    client = SyntheticLateOmissionClient(reading, mixed)

    select_introduction_audience(client, result, reading)

    assert len(client.reviews) == 4
    assert reading.audience_selection['independent_review']['accepted'] is True
    assert reading.audience_part_ids == ['part-0', 'part-1', 'part-2']
    before_late_recovery = client.reviews[2]['decisions']
    decisions = reading.audience_selection['decisions']
    assert decisions[1] == before_late_recovery[1]
    assert decisions[0]['reason'] == before_late_recovery[0]['reason']
    assert decisions[0]['required_meanings'][:2] == before_late_recovery[0]['required_meanings']
    assert decisions[2]['include'] is True
    assert decisions[2]['required_meanings'][0]['meaning'] == reading.parts[2].source_text
    if mixed:
        assert len(client.resolutions) == 2 and not client.addition_requests
        assert decisions[0]['required_meanings'][-1]['meaning'] == 'Local deployment requires onsite review.'
        assert len(client.reviews[-1]['meaning_resolution']['finding_dispositions']) == 2
        assert client.reviews[-1]['meaning_resolution']['semantic_approval'] is False
    else:
        assert len(client.resolutions) == 1 and len(client.addition_requests) == 1
        assert decisions[:2] == before_late_recovery[:2]
        assert client.addition_requests[0]['current_decisions'] == before_late_recovery
    assert_source_preserved(reading, original_parts, decisions)


@pytest.mark.parametrize('outcome,reason', [
    ('unchanged_repeat', 'unchanged_rejected_candidate_and_findings'),
    ('paraphrased_repeat', 'no_new_bound_source_findings'),
])
def test_repeated_rejections_stop_without_repairing_again(outcome, reason):
    result, reading = adaptive_recovery_fixture()
    original_parts = deepcopy(reading.parts)
    client = SyntheticAdaptiveRecoveryClient(reading, outcome)

    with pytest.raises(ValueError, match='not independently accepted'):
        select_introduction_audience(client, result, reading)

    assert len(client.reviews) == 4 and len(client.resolutions) == 2
    assert reading.audience_part_ids is None and not reading.audience_selection
    budgets = [audit['introduction_recovery_budget'] for audit in reading.plan_audits
        if 'introduction_recovery_budget' in audit]
    assert budgets[-1]['reason'] == reason
    assert budgets[-1]['repair_allowed'] is False
    assert budgets[-1]['semantic_approval'] is False
    if outcome == 'unchanged_repeat':
        assert client.reviews[2]['current_selection_digest'] == client.reviews[3]['current_selection_digest']
    assert_source_preserved(reading, original_parts, client.reviews[-1]['decisions'])
