"""Semantic coverage follows the source; slide limits apply to audience synthesis."""
from tests.introduction_review_helpers import review_response
from copy import deepcopy
from types import SimpleNamespace

import pytest

from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
from adaptive_document_agent.agent.compact_summary import compact_input, generate_compact_summary
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.introduction_audience import (
    audience_part_ids, coverage_errors, meanings_digest, validate_required_meanings,
)
from adaptive_document_agent.services.summary_validation import presentation_errors
from tests.test_compact_summary_v111 import fixture, Reviewer
from tests.test_introduction_meaning_inventory_v139 import context


def source_fixture():
    result, reading, _ = fixture(1)
    claims = [f'Station {chr(65 + index)} requires operator training before opening.' for index in range(13)]
    text = ' '.join(claims)
    result.document.pages[0].text = text
    reading.source_blocks[0].text = text
    reading.source_blocks[0].char_end = len(text)
    reading.parts[0].source_text = text
    reading.parts[0].facts = []
    return result, reading, claims


class CapacityClient:
    def __init__(self, claims, *, groups=1, accept_final=True, unsupported=False):
        self.claims = claims
        self.groups = groups
        self.accept_final = accept_final
        self.unsupported = unsupported
        self.calls, self.reviews = [], []
        self.chunks = [claims[index * len(claims) // groups:(index + 1) * len(claims) // groups]
                       for index in range(groups)]

    def generate_structured(self, messages, schema, **kwargs):
        self.calls.append(schema.__name__)
        assert kwargs['stage'] == 'presentation' and kwargs['allow_repair'] is False
        if schema.__name__ == 'IntroductionAudienceSelection':
            originals = [' '.join(chunk) for chunk in self.chunks]
            return schema(decisions=[dict(part_id='part-0', include=True,
                reason='The operating prerequisites define service availability.',
                required_meanings=[dict(meaning=value) for value in originals])])
        payload = context(messages)
        if schema.__name__ == 'IntroductionMeaningRevision':
            # The transport allowance includes model reasoning and full JSON.
            from adaptive_document_agent.agent.introduction_meaning_repair import MEANING_REVISION_TOKEN_LIMITS
            assert kwargs['max_tokens'] == MEANING_REVISION_TOKEN_LIMITS[0]
            assert 'invented item limit' in messages[0]['content']
            edits = []
            for item in payload['original_meanings']:
                replacements = self.chunks[item['meaning_index']]
                if self.unsupported and item['meaning_index'] == 0:
                    replacements = ['Station A can open without operator training.', *replacements[1:]]
                edits.append(dict(meaning_id=item['meaning_id'],
                                  required_meanings=[dict(meaning=value) for value in replacements]))
            return schema(edits=edits)
        if schema.__name__ == 'IntroductionMeaningResolution':
            return schema(finding_dispositions=[dict(finding_id=finding['finding_id'],
                classification='already_covered', action='already_covered',
                referenced_meaning_ids=[row['meaning_id'] for row in payload['current_meanings']
                                        if row['part_id'] == finding['part_id']],
                source_quote=payload['source']['parts'][0]['source_text'],
                reason='Untrusted author claims coverage; the independent final reviewer still rejects.')
                for finding in payload['findings']])
        self.reviews.append(deepcopy(payload))
        if len(self.reviews) == 1 and self.groups < len(self.claims):
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                          reason='Keep each station prerequisite independently checkable.')
        assert len(payload['decisions'][0]['required_meanings']) == len(self.claims)
        return review_response(schema, messages, accepted=self.accept_final and not self.unsupported, repair_scope='meanings',
            reason='Every station prerequisite is preserved.' if self.accept_final and not self.unsupported
            else 'The proposed union has not preserved every source prerequisite.')


@pytest.mark.parametrize('groups', [1, 5, 13])
def test_more_than_twelve_meanings_reach_review_without_loss_or_slide_budget_change(groups):
    result, reading, claims = source_fixture()
    original = deepcopy(reading)
    client = CapacityClient(claims, groups=groups)
    select_introduction_audience(client, result, reading)
    expected_calls = ['IntroductionAudienceSelection', 'IntroductionAudienceReview']
    if groups != len(claims):
        expected_calls += ['IntroductionMeaningRevision', 'IntroductionAudienceReview']
    assert client.calls == expected_calls
    assert audience_part_ids(reading) == {'part-0'}
    final = reading.audience_selection['decisions'][0]
    assert [meaning['meaning'] for meaning in final['required_meanings']] == claims
    assert all(meaning['source_quote'] == original.parts[0].source_text for meaning in final['required_meanings'])
    assert reading.parts == original.parts and reading.source_blocks == original.source_blocks
    assert reading.max_intro_slides == original.max_intro_slides == 5
    author_input, _ = compact_input(reading)
    assert len(author_input['parts'][0]['required_meanings']) == len(claims)
    if groups != len(claims):
        first = client.reviews[0]['decisions']
        assert client.reviews[1]['meaning_revision_base'] == first
        assert [(d['part_id'], d['include'], d['reason']) for d in first] == [
            (d['part_id'], d['include'], d['reason']) for d in client.reviews[1]['decisions']]


@pytest.mark.parametrize('unsupported', [False, True])
def test_large_revised_inventory_still_requires_final_independent_source_and_union_approval(unsupported):
    result, reading, claims = source_fixture()
    client = CapacityClient(claims, accept_final=False, unsupported=unsupported)
    with pytest.raises(ValueError, match='not independently accepted'):
        select_introduction_audience(client, result, reading)
    assert len(client.reviews) == 3
    assert len(client.reviews[-1]['decisions'][0]['required_meanings']) == len(claims)
    assert reading.audience_part_ids is None and not reading.audience_selection
    assert client.calls.count('IntroductionMeaningRevision') == 1


@pytest.mark.parametrize('defect', ['empty_quote', 'wrong_owner_quote', 'duplicate_meaning', 'empty_meaning'])
def test_large_inventory_keeps_literal_owned_evidence_and_duplicate_checks(defect):
    _, reading, claims = source_fixture()
    values = [dict(meaning=value, source_quote=reading.parts[0].source_text) for value in claims]
    if defect == 'empty_quote':
        values[-1]['source_quote'] = ''
    elif defect == 'wrong_owner_quote':
        values[-1]['source_quote'] = 'Another station permits untrained operation.'
    elif defect == 'duplicate_meaning':
        values[-1]['meaning'] = values[0]['meaning']
    else:
        values[-1]['meaning'] = ' '
    with pytest.raises(ValueError, match='exact owned source quotation'):
        validate_required_meanings(reading, [dict(part_id='part-0', include=True, required_meanings=values)])


@pytest.mark.parametrize('defect', [None, 'missing', 'duplicate', 'out_of_range'])
def test_all_thirteen_coverage_indices_remain_mandatory(defect):
    _, reading, claims = source_fixture()
    meanings = [dict(meaning=claim, source_quote=reading.parts[0].source_text) for claim in claims]
    checks = [dict(meaning_index=index, covered=True, summary_quote=claim,
                   reason='The exact prerequisite is visible in source-owned copy.')
              for index, claim in enumerate(claims)]
    if defect == 'missing':
        checks.pop()
    elif defect == 'duplicate':
        checks[-1]['meaning_index'] = 0
    elif defect == 'out_of_range':
        checks[-1]['meaning_index'] = len(claims)
    pages = [SimpleNamespace(items=[SimpleNamespace(part_ids=['part-0'], text=' '.join(claims))])]
    errors = coverage_errors(dict(part_id='part-0', coverage=checks), meanings, pages)
    assert bool(errors) is (defect is not None)


def test_mutating_thirteenth_meaning_invalidates_existing_export_review():
    result, reading, claims = source_fixture()
    select_introduction_audience(CapacityClient(claims), result, reading)
    draft = dict(pages=[dict(title='Station prerequisites', items=[dict(label='Operator training',
        text=' '.join(group), fact_ids=['f0'])]) for group in (claims[:7], claims[7:])])
    company = generate_compact_summary(Reviewer(draft), result, reading, CompanyProfile(summary_review=reading))
    reading.status = 'complete'
    assert not presentation_errors(reading, company.summary_pages, result)
    original_digest = meanings_digest(reading)
    reading.audience_selection['decisions'][0]['required_meanings'][12]['meaning'] += ' An additional certificate is required.'
    assert meanings_digest(reading) != original_digest
    errors = presentation_errors(reading, company.summary_pages, result)
    assert isinstance(errors, list) and any('independent review' in error for error in errors)
