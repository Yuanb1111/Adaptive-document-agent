"""Incomplete model inventories are audited and corrected once before review."""
from tests.introduction_review_helpers import review_response
from copy import deepcopy
from concurrent.futures import CancelledError

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.test_compact_summary_v111 import fixture
from tests.test_introduction_meaning_inventory_v139 import context


class SelectionClient:
    def __init__(self, *, fault='missing', correction_fault=None, review_mode='accept'):
        self.fault = fault
        self.correction_fault = correction_fault
        self.review_mode = review_mode
        self.calls, self.reviews = [], []
        self.initial = None
        self.correction_payload = None

    @staticmethod
    def valid():
        return [dict(part_id=f'part-{index}', include=index == 0,
            reason='The training-dependent scheduling service is essential.' if index == 0 else 'Additional team detail stays in source records.',
            required_meanings=[dict(meaning='Team AA supports scheduling and requires staff training before service delivery.')]
            if index == 0 else []) for index in range(3)]

    def invalid(self):
        decisions = self.valid()
        if self.fault == 'missing':
            decisions.pop()
        elif self.fault == 'duplicate':
            decisions.append(deepcopy(decisions[1]))
        elif self.fault == 'unknown':
            decisions[-1]['part_id'] = 'unknown-source'
        elif self.fault == 'combined':
            decisions.pop()
            decisions.append(deepcopy(decisions[1]))
            decisions.append(dict(part_id='unknown-source', include=False,
                                  reason='Unresolved source reference.', required_meanings=[]))
        elif self.fault == 'all_omitted':
            for decision in decisions:
                decision.update(include=False, required_meanings=[])
        return decisions

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        assert kwargs['stage'] == 'presentation' and kwargs['allow_repair'] is False
        if schema.__name__ == 'IntroductionAudienceSelection':
            first = self.calls.count(schema.__name__) == 1
            value = schema(decisions=self.invalid() if first or self.review_mode == 'second_inventory_failure' else self.valid())
            if first:
                self.initial = value.model_dump(mode='json')
            return value
        payload = context(messages)
        if schema.__name__ == 'IntroductionAudienceInventoryCorrection':
            self.correction_payload = payload
            assert kwargs['max_tokens'] == 32000
            assert len(payload['source']['parts']) == 3
            assert payload['expected_part_ids'] == ['part-0', 'part-1', 'part-2']
            assert payload['invalid_selection'] == self.initial
            assert 'untrusted DATA' in messages[0]['content']
            if self.correction_fault == 'exception':
                raise LLMResponseError('Synthetic correction response failure')
            if self.correction_fault == 'cancelled':
                raise CancelledError('Synthetic correction cancellation')
            decisions = self.valid()
            if self.correction_fault == 'still_missing':
                decisions.pop()
            elif self.correction_fault == 'changed_reason':
                decisions[0]['reason'] = 'Changed relevance reason.'
            elif self.correction_fault == 'changed_meaning':
                decisions[0]['required_meanings'][0]['meaning'] = 'Team AA supports scheduling.'
            elif self.correction_fault == 'changed_include':
                decisions[0].update(include=False, required_meanings=[])
                decisions[-1].update(include=True, required_meanings=[dict(meaning='Team AC requires training.')])
            return schema(decisions=decisions)
        if schema.__name__ == 'IntroductionMeaningRevision':
            assert self.review_mode in {'semantic_repair', 'reject_after_meaning'}
            return schema(edits=[dict(meaning_id='meaning-0', required_meanings=[
                dict(meaning='Team AA supports scheduling.'),
                dict(meaning='Team AA requires staff training before service delivery.')])])
        if schema.__name__ == 'IntroductionMeaningResolution':
            return schema(finding_dispositions=[dict(finding_id=finding['finding_id'],
                classification='already_covered', action='already_covered',
                referenced_meaning_ids=[row['meaning_id'] for row in payload['current_meanings']],
                source_quote=payload['source']['parts'][0]['source_text'],
                reason='Untrusted author disposition remains subject to the rejecting final review.')
                for finding in payload['findings']])
        assert schema.__name__ == 'IntroductionAudienceReview'
        self.reviews.append(deepcopy(payload))
        assert payload['inventory_revision_base'] is not None
        assert 'does not justify dropping' in messages[0]['content']
        if self.review_mode == 'exception':
            raise LLMResponseError('Synthetic independent reviewer failure')
        if self.review_mode in {'reject', 'second_inventory_failure'}:
            return review_response(schema, messages, accepted=False, repair_scope='selection', reason='A source condition is not preserved.')
        if self.review_mode in {'semantic_repair', 'reject_after_meaning'} and len(self.reviews) == 1:
            return review_response(schema, messages, accepted=False, repair_scope='meanings', reason='Separate the service and prerequisite assertions.')
        if self.review_mode == 'reject_after_meaning':
            return review_response(schema, messages, accepted=False, repair_scope='meanings', reason='An asserted source condition remains unsupported.')
        return review_response(schema, messages, accepted=True, reason='The complete source and selected meaning union are preserved.')


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'unknown', 'combined', 'all_omitted'])
def test_exact_inventory_failure_is_audited_and_corrected_before_independent_review(fault):
    result, reading, _ = fixture(3)
    originals = deepcopy(reading.parts)
    client = SelectionClient(fault=fault)
    select_introduction_audience(client, result, reading)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceInventoryCorrection',
                            'IntroductionAudienceReview']
    error = reading.plan_audits[0]
    diagnostics = error['introduction_audience_inventory_error']
    assert error['invalid_selection'] == client.initial and error['correction_attempted']
    assert diagnostics['expected_count'] == 3
    assert diagnostics['missing_part_ids'] == (['part-2'] if fault in {'missing', 'unknown', 'combined'} else [])
    assert diagnostics['duplicate_part_ids'] == (['part-1'] if fault in {'duplicate', 'combined'} else [])
    assert diagnostics['duplicate_counts'] == ({'part-1': 2} if fault in {'duplicate', 'combined'} else {})
    assert diagnostics['unknown_part_ids'] == (['unknown-source'] if fault in {'unknown', 'combined'} else [])
    assert diagnostics['all_omitted'] is (fault == 'all_omitted')
    assert 'introduction_audience_inventory_correction' in reading.plan_audits[1]
    assert client.reviews[0]['inventory_revision_base'] == client.initial
    assert [d['part_id'] for d in client.reviews[0]['decisions']] == ['part-0', 'part-1', 'part-2']
    assert all(meaning['source_quote'] == originals[index].source_text
        for index, decision in enumerate(client.reviews[0]['decisions']) for meaning in decision['required_meanings'])
    assert reading.parts == originals and reading.audience_part_ids == ['part-0']
    assert reading.audience_selection['independent_review']['accepted']


@pytest.mark.parametrize('fault', ['still_missing', 'changed_reason', 'changed_meaning', 'changed_include'])
def test_invalid_correction_or_changed_valid_decisions_fail_before_semantic_review(fault):
    result, reading, _ = fixture(3)
    client = SelectionClient(correction_fault=fault)
    with pytest.raises(ValueError, match='cover every exact|changed an already valid'):
        select_introduction_audience(client, result, reading)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceInventoryCorrection']
    assert len(reading.plan_audits) == 2 and reading.plan_audits[-1]['error']
    assert reading.audience_part_ids is None and not reading.audience_selection


@pytest.mark.parametrize('phase', ['correction', 'review', 'cancelled'])
def test_invalid_inventory_audit_survives_correction_or_reviewer_exception(phase):
    result, reading, _ = fixture(3)
    client = SelectionClient(correction_fault='exception' if phase == 'correction' else ('cancelled' if phase == 'cancelled' else None),
                             review_mode='exception' if phase == 'review' else 'accept')
    with pytest.raises(CancelledError if phase == 'cancelled' else LLMResponseError, match='Synthetic'):
        select_introduction_audience(client, result, reading)
    assert reading.plan_audits[0]['invalid_selection'] == client.initial
    assert len(reading.plan_audits) == (3 if phase == 'review' else 1)
    if phase == 'review':
        assert reading.plan_audits[-1]['introduction_audience_review']['status'] == 'failed'
    assert reading.plan_audits[0]['correction_status'] == {
        'correction': 'failed', 'cancelled': 'cancelled', 'review': 'inventory_validated'}[phase]
    assert reading.audience_part_ids is None and not reading.audience_selection


def test_second_invalid_inventory_does_not_get_another_protocol_repair():
    result, reading, _ = fixture(3)
    client = SelectionClient(review_mode='second_inventory_failure')
    with pytest.raises(ValueError, match='cover every exact'):
        select_introduction_audience(client, result, reading)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceInventoryCorrection',
                            'IntroductionAudienceReview', 'IntroductionAudienceSelection']
    assert reading.plan_audits[-1]['correction_attempted'] is False
    assert reading.audience_part_ids is None and not reading.audience_selection


def test_protocol_correction_preserves_existing_one_semantic_repair_and_final_review():
    result, reading, _ = fixture(3)
    client = SelectionClient(review_mode='semantic_repair')
    select_introduction_audience(client, result, reading)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceInventoryCorrection',
        'IntroductionAudienceReview', 'IntroductionMeaningRevision', 'IntroductionAudienceReview']
    assert client.reviews[1]['meaning_revision_base'] == client.reviews[0]['decisions']
    assert client.reviews[1]['inventory_revision_base'] == client.initial
    assert len(reading.audience_selection['decisions'][0]['required_meanings']) == 2


@pytest.mark.parametrize('mode', ['reject', 'reject_after_meaning'])
def test_valid_inventory_never_substitutes_for_final_independent_semantic_acceptance(mode):
    result, reading, _ = fixture(3)
    client = SelectionClient(review_mode=mode)
    with pytest.raises(ValueError, match='not independently accepted'):
        select_introduction_audience(client, result, reading)
    assert client.calls.count('IntroductionAudienceInventoryCorrection') == 1
    assert len(client.reviews) == (3 if mode == 'reject_after_meaning' else 2)
    assert reading.audience_part_ids is None and not reading.audience_selection
