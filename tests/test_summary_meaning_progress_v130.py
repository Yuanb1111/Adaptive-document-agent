"""A newly exposed issue in the same source part gets one verified additive repair."""
import json
from copy import deepcopy
import pytest

from adaptive_document_agent.agent.compact_summary import CompactSummaryReview, generate_compact_summary
from adaptive_document_agent.agent.summary_meaning_progress import verified_same_part_progress
from adaptive_document_agent.models.presentation import CompanyProfile
from tests.test_compact_summary_v111 import fixture, Reviewer


@pytest.mark.parametrize('resolved', [True, False])
def test_changed_failure_reason_requires_independent_actual_progress(resolved):
    old = [dict(part_id='p', accepted=False, reason='Missing recent reporting period.')]
    new = [dict(part_id='p', accepted=False, reason='Missing independent survey attribution.')]
    class Client:
        calls = 0
        def generate_structured(self, messages, schema, **kwargs):
            self.calls += 1
            context = json.loads(messages[-1]['content'].split('\n',1)[1].rsplit('\n',1)[0])
            assert context['source'] == {'full_source':'Earlier and recent reported periods, with external attribution.'}
            assert context['previous_rejections'] == old and context['current_rejections'] == new
            return schema(parts=[dict(part_id='p', previous_issue_resolved=resolved, reason='Compared actual source-bound current copy.')])
    client, audit = Client(), {}
    assert verified_same_part_progress(client, {'full_source':'Earlier and recent reported periods, with external attribution.'},
        {'copy':'Earlier period'}, {'copy':'Earlier and recent periods'}, old, new, audit=audit) is resolved
    assert client.calls == 1 and audit['same_part_meaning_progress']


def test_unchanged_draft_or_same_failure_never_gets_extra_semantic_repair():
    class Client:
        def generate_structured(self, *args, **kwargs): raise AssertionError('No model request justified')
    verdict = [dict(part_id='p', accepted=False, reason='Missing qualification.')]
    assert not verified_same_part_progress(Client(), {}, {'a':1}, {'a':1}, verdict,
        [dict(part_id='p', accepted=False, reason='Different words for missing qualification.')], audit={})
    assert not verified_same_part_progress(Client(), {}, {'a':1}, {'a':2}, verdict, verdict, audit={})


@pytest.mark.parametrize('resolved', [True, False])
def test_same_part_residual_issue_keeps_first_correction_and_is_still_independently_reviewed(resolved):
    result, review, draft = fixture(1)
    original = draft['pages'][0]['items'][0]
    corrected = deepcopy(original)
    corrected['text'] += ' Training precedes delivery.'
    class Client(Reviewer):
        meanings = 0
        revisions = 0
        def generate_structured(self, messages, schema, **kwargs):
            if schema is CompactSummaryReview:
                self.meanings += 1
                response = super().generate_structured(messages, schema, **kwargs)
                if self.meanings < 3:
                    response.parts[0].accepted = False
                    response.parts[0].reason = ('Missing prerequisite timing.' if self.meanings == 1
                                                else 'Missing prerequisite attribution.')
                return response
            if schema.__name__ == 'SummaryMeaningProgressReview':
                return schema(parts=[dict(part_id='part-0', previous_issue_resolved=resolved,
                    reason='The current paragraph now states timing; attribution remains rejected.')])
            if schema.__name__ == 'SummarySynthesisRevision':
                self.revisions += 1
                if self.revisions == 1:
                    return schema(replacements=[dict(item_id='g0_i0', replacement=corrected)])
                assert schema.model_fields['replacements'].metadata[-1].max_length == 0
                return schema(additions=[dict(group_id='g0', item=dict(label='Delivery condition',
                    text=review.parts[0].facts[0].text, fact_ids=['f0']))])
            return super().generate_structured(messages, schema, **kwargs)
    client = Client(draft)
    if resolved:
        company = generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
        assert company.summary_pages[0].items[0].text == corrected['text']
        assert len(company.summary_pages[0].items) == 2
        assert client.meanings == 3 and client.revisions == 2
        assert review.plan_audits[-1]['content_revision_policy'] == 'additive_meaning_regression'
    else:
        with pytest.raises(ValueError, match='Missing prerequisite attribution'):
            generate_compact_summary(client, result, review, CompanyProfile(summary_review=review))
        assert client.meanings == 2 and client.revisions == 1
