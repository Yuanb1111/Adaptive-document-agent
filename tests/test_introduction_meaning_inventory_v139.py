"""A partial reviewer diagnosis cannot leave other selected assertions unexamined."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from tests.test_compact_summary_v111 import fixture


def context(messages):
    return json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])


class InventoryClient:
    def __init__(self, *, malformed=None, drop_requirement=False, unsupported=False):
        self.malformed = malformed
        self.drop_requirement = drop_requirement
        self.unsupported = unsupported
        self.calls, self.reviews = [], []
        self.inventory = None

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        assert kwargs['stage'] == 'presentation' and kwargs['allow_repair'] is False
        if schema.__name__ == 'IntroductionAudienceSelection':
            meanings = [
                ['Team AA supports scheduling.', 'Team AA staff training is optional before service delivery.'],
                ['Team AB supports scheduling and requires staff training before service delivery.'],
                ['Team AC supports scheduling and requires staff training before service delivery.'],
                [],
            ]
            return schema(decisions=[dict(part_id=f'part-{i}', include=i < 3,
                reason='Distinct delivery team.' if i < 3 else 'Additional team detail stays in source records.',
                required_meanings=[dict(meaning=value) for value in values])
                for i, values in enumerate(meanings)])
        payload = context(messages)
        if schema.__name__ == 'IntroductionMeaningRevision':
            self.inventory = payload['original_meanings']
            assert 'EVERY supplied original meaning' in messages[0]['content']
            assert 'including meanings not mentioned in review_feedback' in messages[0]['content']
            assert len(payload['source']['parts']) == 4
            assert payload['review_feedback'] == 'Team AA training cannot be described as optional.'
            edits = []
            for item in self.inventory:
                team = {'part-0': 'AA', 'part-1': 'AB', 'part-2': 'AC'}[item['part_id']]
                copy = [f'Team {team} supports scheduling.',
                        f'Team {team} requires staff training before service delivery.']
                if item['part_id'] == 'part-0':
                    copy = [copy[item['meaning_index']]]
                if item['part_id'] == 'part-1' and self.drop_requirement:
                    copy = copy[:1]
                if item['part_id'] == 'part-2' and self.unsupported:
                    copy[1] = 'Team AC has no staff training prerequisite.'
                edits.append(dict(meaning_id=item['meaning_id'],
                                  required_meanings=[dict(meaning=value) for value in copy]))
            if self.malformed == 'missing':
                edits.pop(0)  # Even an unchanged, already sound assertion needs coverage.
            elif self.malformed == 'duplicate':
                edits[-1]['meaning_id'] = edits[0]['meaning_id']
            elif self.malformed == 'unknown':
                edits[-1]['meaning_id'] = 'meaning-unknown'
            elif self.malformed == 'empty':
                edits[-1]['required_meanings'] = []
            elif self.malformed == 'reassigned':
                edits[-1]['part_id'] = 'part-3'
            elif self.malformed == 'over-capacity':
                edits[0]['required_meanings'] = [dict(meaning=f'Proposed assertion {i}.') for i in range(12)]
            return schema(edits=list(reversed(edits)))
        self.reviews.append(deepcopy(payload))
        if len(self.reviews) == 1:
            # Simulate a real reviewer naming one defect but missing other bundles.
            return schema(accepted=False, repair_scope='meanings',
                          reason='Team AA training cannot be described as optional.')
        accepted = not self.drop_requirement and not self.unsupported
        return schema(accepted=accepted, repair_scope='meanings', reason='Every source-bound assertion is preserved.'
            if accepted else 'A previously selected training prerequisite is absent or contradicted.')


def test_one_correction_covers_unreported_bundles_and_preserves_each_original_owner():
    result, reading, _ = fixture(4)
    sources = deepcopy(reading.parts)
    client = InventoryClient()
    select_introduction_audience(client, result, reading)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceReview',
                            'IntroductionMeaningRevision', 'IntroductionAudienceReview']
    assert [(item['part_id'], item['meaning_index']) for item in client.inventory] == [
        ('part-0', 0), ('part-0', 1), ('part-1', 0), ('part-2', 0)]
    first, final = [value['decisions'] for value in client.reviews]
    assert client.reviews[1]['meaning_revision_base'] == first
    assert [(d['part_id'], d['include'], d['reason']) for d in first] == [
        (d['part_id'], d['include'], d['reason']) for d in final]
    assert final[-1] == first[-1]
    for index, decision in enumerate(final[:-1]):
        assert len(decision['required_meanings']) == 2
        assert all(value['source_quote'] == sources[index].source_text
                   for value in decision['required_meanings'])
        assert decision['required_meanings'][0]['meaning'].endswith('supports scheduling.')
        assert decision['required_meanings'][1]['meaning'].endswith('requires staff training before service delivery.')
    assert reading.parts == sources
    assert reading.audience_part_ids == ['part-0', 'part-1', 'part-2']
    revision = next(audit for audit in reading.plan_audits if 'introduction_meaning_revision' in audit)
    assert len(revision['meaning_inventory']) == 4


@pytest.mark.parametrize('malformed', ['missing', 'duplicate', 'unknown', 'empty', 'reassigned', 'over-capacity'])
def test_incomplete_inventory_empty_replacements_and_owner_reassignment_fail_closed(malformed):
    result, reading, _ = fixture(4)
    client = InventoryClient(malformed=malformed)
    with pytest.raises(ValueError):
        select_introduction_audience(client, result, reading)
    assert client.calls.count('IntroductionMeaningRevision') == 1
    assert len(client.reviews) == 1
    assert reading.audience_part_ids is None and not reading.audience_selection


@pytest.mark.parametrize('defect', ['drop_requirement', 'unsupported'])
def test_complete_mapping_cannot_bypass_final_semantic_review_or_trigger_more_retries(defect):
    result, reading, _ = fixture(4)
    client = InventoryClient(**{defect: True})
    with pytest.raises(ValueError, match='not independently accepted'):
        select_introduction_audience(client, result, reading)
    assert len(client.calls) == 4 and len(client.reviews) == 2
    assert reading.audience_part_ids is None and not reading.audience_selection
    rejected = [audit for audit in reading.plan_audits if 'introduction_audience_attempt' in audit]
    assert len(rejected) == 2 and all(not audit['review']['accepted'] for audit in rejected)
