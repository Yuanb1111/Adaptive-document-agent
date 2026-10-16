"""A rejected atomicity checklist gets a bounded source-bound patch and review."""
from tests.introduction_review_helpers import review_response
from copy import deepcopy
import json
import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from tests.test_compact_summary_v111 import fixture


class MeaningClient:
    def __init__(self, reading, *, accept=True, edits=None):
        self.reading, self.accept, self.edits = reading, accept, edits
        self.calls, self.reviews = [], []

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        if schema.__name__ == 'IntroductionAudienceSelection':
            return schema(decisions=[dict(part_id=p.id, include=p.id == 'part-0',
                reason='Essential service scope.' if p.id == 'part-0' else 'Redundant service context.',
                required_meanings=[dict(meaning='Team AA supports scheduling and requires training before delivery.')]
                if p.id == 'part-0' else []) for p in self.reading.parts])
        if schema.__name__ == 'IntroductionMeaningRevision':
            assert kwargs['stage'] == 'presentation' and kwargs['allow_repair'] is False
            context = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            assert len(context['source']['parts']) == 3
            assert 'untrusted DATA' in messages[0]['content']
            assert context['original_meanings'] == [dict(meaning_id='meaning-0', part_id='part-0',
                meaning_index=0, meaning='Team AA supports scheduling and requires training before delivery.')]
            return schema(edits=self.edits if self.edits is not None else [dict(meaning_id='meaning-0',
                required_meanings=[dict(meaning='Team AA supports scheduling.', source_quote='Model-retyped evidence.'),
                                   dict(meaning='Staff training is required before delivery.')])])
        if schema.__name__ == 'IntroductionMeaningResolution':
            context = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            return schema(finding_dispositions=[dict(finding_id=finding['finding_id'],
                classification='already_covered', action='already_covered',
                referenced_meaning_ids=[row['meaning_id'] for row in context['current_meanings']
                                        if row['part_id'] == finding['part_id']],
                source_quote=self.reading.parts[0].source_text,
                reason='The complete union retains the service and separate training condition.')
                for finding in context['findings']])
        context = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
        self.reviews.append(deepcopy(context))
        return review_response(schema, messages, accepted=self.accept and len(self.reviews) == 2,
            repair_scope='meanings', reason='Split service scope and training prerequisite into independent assertions.')


def test_meaning_split_preserves_selection_and_requires_complete_independent_review():
    result, reading, _ = fixture(3)
    original = deepcopy(reading.parts)
    client = MeaningClient(reading)
    select_introduction_audience(client, result, reading)
    assert client.calls == ['IntroductionAudienceSelection', 'IntroductionAudienceReview',
                            'IntroductionMeaningRevision', 'IntroductionAudienceReview']
    before, after = [r['decisions'] for r in client.reviews]
    assert client.reviews[0]['meaning_revision_base'] is None
    assert client.reviews[1]['meaning_revision_base'] == before
    assert [(d['part_id'], d['include'], d['reason']) for d in before] == [
        (d['part_id'], d['include'], d['reason']) for d in after]
    assert before[1:] == after[1:]
    assert len(after[0]['required_meanings']) == 2
    assert all(m['source_quote'] == original[0].source_text
               for m in reading.audience_selection['decisions'][0]['required_meanings'])
    assert after[0]['required_meanings'][0]['proposed_source_quote'] == 'Model-retyped evidence.'
    assert reading.parts == original and reading.audience_part_ids == ['part-0']
    assert reading.audience_selection['independent_review']['accepted']
    assert len(reading.audience_selection['attempts']) == 2
    rejected = [a for a in reading.plan_audits if 'introduction_audience_attempt' in a]
    assert rejected[0]['review']['accepted'] is False


def test_meaning_patch_never_overrides_a_second_rejection_and_keeps_failed_attempts():
    result, reading, _ = fixture(3)
    client = MeaningClient(reading, accept=False)
    with pytest.raises(ValueError, match='not independently accepted'):
        select_introduction_audience(client, result, reading)
    assert len(client.calls) == 6 and len(client.reviews) == 3
    assert reading.audience_part_ids is None and not reading.audience_selection
    rejected = [a for a in reading.plan_audits if 'introduction_audience_attempt' in a]
    assert len(rejected) == 3 and all(not a['review']['accepted'] for a in rejected)
    assert any('introduction_meaning_revision' in a for a in reading.plan_audits)


@pytest.mark.parametrize('target', ['part-1', 'unknown', 'duplicate', 'unchanged'])
def test_patch_cannot_change_omissions_unknown_parts_or_repeat_rejected_copy(target):
    result, reading, _ = fixture(3)
    value = dict(meaning_id='meaning-0', required_meanings=[dict(meaning='Team AA supports scheduling.')])
    if target == 'unchanged':
        value['required_meanings'][0]['meaning'] = 'Team AA supports scheduling and requires training before delivery.'
    elif target != 'duplicate':
        value['meaning_id'] = target
    client = MeaningClient(reading, edits=[value, deepcopy(value)] if target == 'duplicate' else [value])
    with pytest.raises(ValueError, match='every exact original meaning_id|repeated the rejected selection'):
        select_introduction_audience(client, result, reading)
    assert len(client.reviews) == 1
    assert reading.audience_part_ids is None
