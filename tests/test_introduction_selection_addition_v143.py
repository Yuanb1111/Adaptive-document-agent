"""A late omission correction preserves the already repaired semantic inventory."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.services.introduction_audience import audience_part_ids
from adaptive_document_agent.services.llm.exceptions import LLMResponseError
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_compact_summary_v111 import fixture


class AdditionClient:
    """Twelve original assertions expand to twenty before one extra part is selected."""
    def __init__(self, reading, *, fault=None, stale=False):
        self.reading, self.fault, self.stale = reading, fault, stale
        self.calls, self.reviews = [], []
        self.atomic = [f'Station {index} requires a trained operator.' for index in range(1, 21)]
        reading.parts[0].source_text = ' '.join(self.atomic)
        self.initial = [' '.join(self.atomic[i:i + 2]) for i in range(0, 16, 2)] + self.atomic[16:]
        reading.parts[1].source_text = 'Service delivery is suspended during mandatory safety inspections.'

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema.__name__ == 'IntroductionAudienceSelection':
            return schema(decisions=[dict(part_id=p.id, include=index == 0,
                reason='Core operating prerequisites.' if index == 0 else 'Initially treated as later detail.',
                required_meanings=[dict(meaning=m) for m in self.initial] if index == 0 else [])
                for index, p in enumerate(self.reading.parts)])
        payload = review_payload(messages)
        if schema.__name__ == 'IntroductionMeaningRevision':
            assert len(payload['original_meanings']) == 12
            return schema(edits=[dict(meaning_id=value['meaning_id'], required_meanings=[dict(meaning=m)
                for m in (self.atomic[index * 2:index * 2 + 2] if index < 8 else [self.atomic[index + 8]])])
                for index, value in enumerate(payload['original_meanings'])])
        if schema.__name__ == 'IntroductionAudienceSelectionAddition':
            assert payload['allowed_part_ids'] == ['part-1']
            assert len(payload['source']['parts']) == 3
            assert len(payload['current_decisions'][0]['required_meanings']) == 20
            if self.fault == 'exception':
                raise LLMResponseError('Addition response unavailable')
            values = [dict(part_id='part-1', include=True, reason='Essential service availability condition.',
                required_meanings=[dict(meaning='Service delivery is suspended during mandatory safety inspections.')])]
            if self.fault == 'missing': values = []
            elif self.fault == 'duplicate': values += deepcopy(values)
            elif self.fault == 'unknown': values[0]['part_id'] = 'unknown'
            elif self.fault == 'protected': values.append(deepcopy(payload['current_decisions'][0]))
            elif self.fault == 'remains_omitted': values[0].update(include=False, required_meanings=[])
            elif self.fault == 'empty_meanings': values[0]['required_meanings'] = []
            elif self.fault == 'unsupported': values[0]['required_meanings'][0]['meaning'] = 'Delivery never requires safety inspections.'
            elif self.fault == 'reassigned': values[0]['required_meanings'][0]['meaning'] = self.atomic[0]
            return schema(decisions=values)
        assert schema.__name__ == 'IntroductionAudienceReview'
        self.reviews.append(deepcopy(payload))
        if len(self.reviews) == 1:
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='Split independent stations into independently checkable assertions.')
        current = payload['current_meanings']
        assert len(payload['decisions'][0]['required_meanings']) == 20
        if self.stale and len(self.reviews) == 2:
            target = current[0]
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='Earlier bundled station wording is not atomic.', findings=[dict(kind='meaning',
                    part_id=target['part_id'], meaning_id=target['meaning_id'], current_meaning=self.initial[0],
                    source_quote=target['source_quote'], reason='Split the old bundled sentence.')])
        if not payload['decisions'][1]['include']:
            return review_response(schema, messages, accepted=False, repair_scope='selection',
                reason='The service interruption condition is essential context.', findings=[dict(kind='omitted_part',
                    part_id='part-1', source_quote=self.reading.parts[1].source_text,
                    reason='Include the mandatory service suspension condition.')])
        if self.fault in ('unsupported', 'reassigned', 'final_reject', 'another_omission'):
            target = current[-1]
            findings = [dict(kind='meaning', part_id=target['part_id'], meaning_id=target['meaning_id'],
                current_meaning=target['meaning'], source_quote=target['source_quote'],
                reason='The addition does not preserve its owning source condition.')]
            if self.fault == 'another_omission':
                findings = [dict(kind='omitted_part', part_id='part-2',
                    source_quote=self.reading.parts[2].source_text, reason='Another essential source omission remains.')]
            return review_response(schema, messages, accepted=False, repair_scope='selection',
                reason='The final source union remains unacceptable.', findings=findings)
        if self.fault == 'final_exception':
            raise LLMResponseError('Final independent review unavailable')
        return review_response(schema, messages, accepted=True,
            reason='The complete source and preserved selected union support this introduction.')


@pytest.mark.parametrize('stale', [False, True])
def test_new_omission_addition_preserves_twenty_repaired_meanings_and_requires_fresh_review(stale):
    result, reading, _ = fixture(3)
    client = AdditionClient(reading, stale=stale)
    original_parts = deepcopy(reading.parts)
    select_introduction_audience(client, result, reading)
    assert client.calls.count('IntroductionAudienceSelection') == 1
    assert client.calls.count('IntroductionMeaningRevision') == 1
    assert client.calls.count('IntroductionAudienceSelectionAddition') == 1
    assert client.calls.count('IntroductionAudienceReview') == (4 if stale else 3)
    before = client.reviews[-2]['decisions']
    after = client.reviews[-1]['decisions']
    assert before[0] == after[0] and before[2] == after[2]
    assert [m['meaning'] for m in after[0]['required_meanings']] == client.atomic
    assert after[1]['include'] and len(after[1]['required_meanings']) == 1
    assert audience_part_ids(reading) == {'part-0', 'part-1'}
    assert reading.parts == original_parts
    assert client.reviews[-1]['meaning_revision_base'] == client.reviews[0]['decisions']
    assert reading.audience_selection['independent_review']['accepted'] is True
    audits = [a['introduction_audience_selection_addition'] for a in reading.plan_audits
              if 'introduction_audience_selection_addition' in a]
    assert len(audits) == 1 and audits[0]['status'] == 'inventory_validated'
    assert audits[0]['decisions_before'] == before


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'unknown', 'protected', 'remains_omitted', 'empty_meanings'])
def test_addition_cannot_rewrite_drop_or_reassign_the_protected_inventory(fault):
    result, reading, _ = fixture(3)
    client = AdditionClient(reading, fault=fault)
    with pytest.raises(ValueError, match='each exact newly required part once'):
        select_introduction_audience(client, result, reading)
    assert client.calls.count('IntroductionAudienceSelectionAddition') == 1
    assert client.calls.count('IntroductionAudienceReview') == 2
    assert reading.audience_part_ids is None and not reading.audience_selection
    assert reading.plan_audits[-1]['introduction_audience_selection_addition']['status'] == 'invalid_addition'


@pytest.mark.parametrize('fault', ['unsupported', 'reassigned', 'final_reject', 'another_omission'])
def test_final_independent_rejection_still_blocks_with_no_second_addition(fault):
    result, reading, _ = fixture(3)
    client = AdditionClient(reading, fault=fault)
    with pytest.raises(ValueError, match='not independently accepted'):
        select_introduction_audience(client, result, reading)
    assert client.calls.count('IntroductionAudienceSelectionAddition') == 1
    assert client.calls.count('IntroductionAudienceReview') == 3
    assert reading.audience_part_ids is None and not reading.audience_selection
    assert client.reviews[-1]['decisions'][0] == client.reviews[-2]['decisions'][0]
    assert reading.plan_audits[-1]['review']['accepted'] is False


@pytest.mark.parametrize('fault', ['exception', 'final_exception'])
def test_model_failure_keeps_before_after_audits_without_approval(fault):
    result, reading, _ = fixture(3)
    client = AdditionClient(reading, fault=fault)
    with pytest.raises(LLMResponseError):
        select_introduction_audience(client, result, reading)
    record = next(a['introduction_audience_selection_addition'] for a in reading.plan_audits
                  if 'introduction_audience_selection_addition' in a)
    assert len(record['decisions_before'][0]['required_meanings']) == 20
    if fault == 'exception':
        assert record['status'] == 'failed'
    else:
        assert record['status'] == 'inventory_validated' and record['decisions_after']
        assert reading.plan_audits[-1]['introduction_audience_review']['status'] == 'failed'
    assert not reading.audience_selection
