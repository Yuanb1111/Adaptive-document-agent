"""Synthetic author/reviewer fixtures exercise mixed repair through the real flow.

These offline responses establish protocol behavior, never real model quality.
"""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_compact_summary_v111 import fixture


def mixed_flow_fixture():
    result, reading, _ = fixture(4)
    texts = [
        'The platform schedules appointments only after staff training. '
        'The platform supports staff coordination. Local deployment requires onsite review.',
        'The service serves local customers. Remote access is unavailable.',
        'The service may be interrupted by supply failures and limited staffing.',
        'A prior pilot used the same scheduling workflow.',
    ]
    for part, text in zip(reading.parts, texts):
        part.source_text = text
    return result, reading


class SyntheticMixedFlowGateway:
    """Explicitly synthetic author and fresh reviewer; no provider is accessed."""

    def __init__(self, reading, final_verdict):
        self.reading, self.final_verdict = reading, final_verdict
        self.calls, self.reviews, self.resolution_requests = [], [], []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema.__name__ == 'IntroductionAudienceSelection':
            return schema(decisions=[dict(part_id=part.id, include=index < 2,
                reason='Core service scope.' if index < 2 else 'Detail retained in source records.',
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
            self.resolution_requests.append(deepcopy(payload))
            assert [row['kind'] for row in payload['findings']] == [
                'meaning', 'omitted_part', 'included_part', 'included_part']
            return schema(edits=[dict(meaning_id='part-0:meaning-1', required_meanings=[
                dict(meaning='The platform schedules appointments only after staff training.')])],
                additions=[dict(part_id='part-0', required_meanings=[
                    dict(meaning='Local deployment requires onsite review.')]),
                    dict(part_id='part-1', required_meanings=[
                        dict(meaning='Remote access is unavailable.')])],
                inclusions=[dict(part_id='part-2', include=True,
                    reason='Operational interruption is an essential service limitation.',
                    required_meanings=[dict(meaning=self.reading.parts[2].source_text)])],
                finding_dispositions=[dict(finding_id=f'finding-{index}',
                    classification='missing_qualification' if index == 0 else 'new_assertion',
                    action='corrected', referenced_meaning_ids=['part-0:meaning-1'] if index == 0 else [],
                    source_quote=self.reading.parts[part_index].source_text,
                    reason='Synthetic source-bound correction; independent review remains required.')
                    for index, part_index in enumerate([0, 2, 0, 1])])
        assert schema.__name__ == 'IntroductionAudienceReview'
        self.reviews.append(deepcopy(payload))
        if len(self.reviews) == 1:
            row = payload['current_meanings'][0]
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='Separate the independent scheduling and coordination assertions.', findings=[dict(
                    kind='meaning', issue_type='atomicity', part_id=row['part_id'],
                    meaning_id=row['meaning_id'], current_meaning=row['meaning'],
                    source_quote=self.reading.parts[0].source_text,
                    reason='Scheduling and coordination are independently checkable assertions.')])
        if len(self.reviews) == 2:
            row = payload['current_meanings'][0]
            findings = [dict(kind='meaning', issue_type='missing_qualification', part_id='part-0',
                meaning_id=row['meaning_id'], current_meaning=row['meaning'],
                source_quote=self.reading.parts[0].source_text, reason='Staff training is necessary.'),
                dict(kind='omitted_part', issue_type='new_assertion', part_id='part-2',
                    source_quote=self.reading.parts[2].source_text,
                    reason='Operational interruption is essential introductory context.'),
                dict(kind='included_part', issue_type='new_assertion', part_id='part-0',
                    source_quote=self.reading.parts[0].source_text,
                    reason='The onsite deployment requirement is essential.'),
                dict(kind='included_part', issue_type='new_assertion', part_id='part-1',
                    source_quote=self.reading.parts[1].source_text,
                    reason='The local-only scope is essential.')]
            return review_response(schema, messages, accepted=False, repair_scope='selection',
                reason='Correct the qualification, two included assertions and omitted limitation.', findings=findings)
        assert payload['current_selection_digest'] != self.reviews[1]['current_selection_digest']
        assert payload['meaning_resolution']['semantic_approval'] is False
        assert len(payload['meaning_resolution']['finding_dispositions']) == 4
        if self.final_verdict == 'unavailable':
            raise LLMResponseError('Synthetic final reviewer unavailable; never auto-approve.')
        if self.final_verdict == 'stale' and len(self.reviews) == 3:
            return schema(accepted=True, reason='Synthetic stale acceptance must be rejected.',
                selection_digest=self.reviews[1]['current_selection_digest'])
        return review_response(schema, messages, accepted=self.final_verdict != 'reject',
            reason='Synthetic fresh reviewer independently checks the complete revised union.')


@pytest.mark.parametrize('final_verdict', ['accept', 'reject', 'unavailable', 'stale'])
def test_one_mixed_resolution_repairs_all_four_findings_and_requires_fresh_review(final_verdict):
    result, reading = mixed_flow_fixture()
    original_parts = deepcopy(reading.parts)
    gateway = SyntheticMixedFlowGateway(reading, final_verdict)
    if final_verdict in {'accept', 'stale'}:
        select_introduction_audience(gateway, result, reading)
        assert reading.audience_part_ids == ['part-0', 'part-1', 'part-2']
        assert reading.audience_selection['independent_review']['accepted'] is True
        decisions = reading.audience_selection['decisions']
    else:
        with pytest.raises((ValueError, LLMResponseError)):
            select_introduction_audience(gateway, result, reading)
        assert not reading.audience_selection and reading.audience_part_ids is None
        decisions = gateway.reviews[-1]['decisions']
    assert reading.parts == original_parts
    assert gateway.calls[:5] == ['IntroductionAudienceSelection', 'IntroductionAudienceReview',
        'IntroductionMeaningRevision', 'IntroductionAudienceReview', 'IntroductionMeaningResolution']
    assert gateway.calls[5:] == ['IntroductionAudienceReview'] * (2 if final_verdict == 'stale' else 1)
    assert len(gateway.resolution_requests) == 1
    before = gateway.reviews[1]['decisions']
    assert decisions[3] == before[3]
    assert decisions[0]['reason'] == before[0]['reason']
    assert decisions[1]['reason'] == before[1]['reason']
    assert decisions[0]['required_meanings'][1] == before[0]['required_meanings'][1]
    assert decisions[1]['required_meanings'][0] == before[1]['required_meanings'][0]
    assert decisions[0]['required_meanings'][0]['meaning'].endswith('only after staff training.')
    assert decisions[0]['required_meanings'][-1]['meaning'] == 'Local deployment requires onsite review.'
    assert decisions[1]['required_meanings'][-1]['meaning'] == 'Remote access is unavailable.'
    assert decisions[2]['include'] is True
    assert decisions[2]['required_meanings'][0]['meaning'] == reading.parts[2].source_text
    for decision in decisions:
        for meaning in decision['required_meanings']:
            assert meaning['source_quote'] == next(part.source_text for part in reading.parts
                if part.id == decision['part_id'])
