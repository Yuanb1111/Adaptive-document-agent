"""Splitting one claim must not make its sibling inherit an older rejection."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_compact_summary_v111 import fixture


class SplitConditionClient:
    def __init__(self, reading, *, reject_again=False):
        self.reading = reading
        self.reject_again = reject_again
        self.reviews = 0
        self.resolutions = 0

    def generate_structured(self, messages, schema, **kwargs):
        assert kwargs['allow_repair'] is False
        if schema.__name__ == 'IntroductionAudienceSelection':
            assert 'conditions under which it holds is ONE assertion' in messages[0]['content']
            return schema(decisions=[
                dict(part_id='part-0', include=True, reason='Service and operating scope.',
                     required_meanings=[dict(meaning=text) for text in (
                         'The platform supports scheduling and coordination.',
                         'The sensor detects objects at 20 cm when operating at 2 m/s.',
                         'Its benchmark is standard Q.')]),
                dict(part_id='part-1', include=True, reason='Delivery scope.',
                     required_meanings=[dict(meaning='The service supports remote delivery.')]),
                dict(part_id='part-2', include=False, reason='Historical context.',
                     required_meanings=[])])
        payload = review_payload(messages)
        if schema.__name__ == 'IntroductionMeaningRevision':
            assert 'conditions under which it holds is ONE assertion' in messages[0]['content']
            replacements = [
                ['The platform supports scheduling.', 'The platform supports coordination.'],
                ['The sensor detects objects at 20 cm.'],
                ['Its benchmark is the revised standard Q.'],
                ['The service supports remote delivery.']]
            return schema(edits=[dict(meaning_id=row['meaning_id'],
                required_meanings=[dict(meaning=text) for text in texts])
                for row, texts in zip(payload['original_meanings'], replacements, strict=True)])
        if schema.__name__ == 'IntroductionMeaningResolution':
            self.resolutions += 1
            finding = payload['findings'][0]
            if self.resolutions == 1:
                corrected = 'The service supports remote delivery after enrollment.'
            elif self.reject_again:
                corrected = 'The sensor can detect objects at 20 cm.'
            else:
                corrected = 'The sensor detects objects at 20 cm when operating at 2 m/s.'
            return schema(edits=[dict(meaning_id=finding['meaning_id'],
                required_meanings=[dict(meaning=corrected)])], finding_dispositions=[
                    dict(finding_id='finding-0', classification='missing_qualification', action='corrected',
                         referenced_meaning_ids=[finding['meaning_id']], reason='Restore the source condition.')])
        assert schema.__name__ == 'IntroductionAudienceReview'
        self.reviews += 1
        meanings = payload['current_meanings']
        if self.reviews == 4 and not self.reject_again:
            assert any(m['meaning'] == 'The sensor detects objects at 20 cm when operating at 2 m/s.'
                       for m in meanings)
            return review_response(schema, messages, accepted=True, reason='Synthetic independent acceptance.')
        if self.reviews == 1:
            targets = [(meanings[0], 'atomicity'), (meanings[2], 'missing_qualification')]
        elif self.reviews == 2:
            targets = [(meanings[-1], 'missing_qualification')]
        else:
            targets = [(meanings[2], 'missing_qualification')]
        return review_response(schema, messages, accepted=False, repair_scope='meanings',
            reason='Source-bound condition or split is required.', findings=[
                dict(kind='meaning', issue_type=kind, part_id=m['part_id'], meaning_id=m['meaning_id'],
                     current_meaning=m['meaning'], reason='Retain the complete owned source condition.')
                for m, kind in targets])


@pytest.mark.parametrize('reject_again', [False, True])
def test_new_condition_after_renumbering_gets_a_bound_repair_but_repeated_defect_stops(reject_again):
    result, reading, _ = fixture(3)
    reading.parts[0].source_text = (
        'The platform supports scheduling and coordination. The sensor detects objects at 20 cm '
        'when operating at 2 m/s. Its benchmark is the revised standard Q.')
    reading.parts[1].source_text = 'The service supports remote delivery after enrollment.'
    original = deepcopy(reading.parts)
    # A previous failed run may retain diagnostics. Its address mapping must
    # not rename the new invocation's initial assertions.
    reading.plan_audits.append({'meaning_lineage': {
        'part-0:meaning-2': ['obsolete:meaning-1'],
        'part-0:meaning-3': ['obsolete:meaning-1']}})
    client = SplitConditionClient(reading, reject_again=reject_again)
    if reject_again:
        with pytest.raises(ValueError, match='not independently accepted'):
            select_introduction_audience(client, result, reading)
        assert not reading.audience_selection
    else:
        select_introduction_audience(client, result, reading)
        assert reading.audience_selection['independent_review']['accepted']
    assert client.reviews == 4 and client.resolutions == 2
    budgets = [row['introduction_recovery_budget'] for row in reading.plan_audits
               if 'introduction_recovery_budget' in row]
    assert budgets[0]['reason'] == 'new_bound_source_findings'
    assert budgets[0]['novel_finding_indices'] == [0]
    if reject_again:
        assert budgets[-1]['reason'] == 'no_new_bound_source_findings'
    assert reading.parts == original


def test_merge_keeper_inherits_removed_assertion_identity():
    from adaptive_document_agent.agent.introduction_recovery import IntroductionRepairBudget
    from tests.test_introduction_meaning_merges_v217 import fixture as merge_fixture, resolve
    from tests.test_introduction_resolution_feedback_v181 import Replies

    data = merge_fixture()
    _, reading, _, _, _, response = data
    _, ledger = resolve(Replies(response), data)
    budget = IntroductionRepairBudget()
    budget._track_revisions(reading)
    assert budget.meaning_origins['part-0:meaning-2'] == {
        'part-0:meaning-2', 'part-0:meaning-4'}
    assert 'part-0:meaning-4' not in budget.meaning_origins
    assert ledger['semantic_approval'] is False
