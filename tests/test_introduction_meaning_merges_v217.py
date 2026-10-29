"""Redundancy consolidation is explicit and never grants semantic acceptance."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_audience import RequiredMeaning, select_introduction_audience
from adaptive_document_agent.agent.introduction_audience_review import IntroductionAudienceReview, review_current_selection
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    IntroductionMeaningResolution, MeaningResolutionEdit, apply_meaning_resolution, resolve_meaning_findings,
)
from adaptive_document_agent.agent.introduction_resolution_feedback import UnappliedMeaningCorrection
from tests.test_introduction_meaning_resolution_v147 import resolution_fixture
from tests.test_introduction_resolution_feedback_v181 import Replies
from tests.introduction_review_helpers import review_response, review_payload


def fixture():
    result, reading, source, selection, _, _ = resolution_fixture()
    selection.decisions[0].required_meanings.append(RequiredMeaning(
        meaning='Before delivery, staff training is required.', source_quote=source['parts'][0]['source_text']))
    findings = [dict(finding_id='finding-0', kind='meaning', issue_type='atomicity',
        part_id='part-0', meaning_id='part-0:meaning-4',
        current_meaning=selection.decisions[0].required_meanings[3].meaning,
        source_quote=source['parts'][0]['source_text'], reason='Same-part training assertion duplicates meaning-2.')]
    response = IntroductionMeaningResolution(merges=[dict(meaning_id='part-0:meaning-4',
        retained_meaning_ids=['part-0:meaning-2'], reason='The surviving assertion retains training and its delivery condition.')],
        finding_dispositions=[dict(finding_id='finding-0', classification='atomicity', action='corrected',
            referenced_meaning_ids=['part-0:meaning-4', 'part-0:meaning-2'],
            source_quote=source['parts'][0]['source_text'], reason='Consolidate this duplicate without changing its keeper.')])
    return result, reading, source, selection, findings, response


def resolve(client, values):
    _, reading, source, selection, findings, _ = values
    verdict = IntroductionAudienceReview(accepted=False, reason='Duplicate assertion needs consolidation.',
        repair_scope='meanings', findings=[{k: v for k, v in f.items() if k != 'finding_id'} for f in findings])
    return resolve_meaning_findings(client, source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading)


def test_explicit_merge_preserves_surviving_meanings_and_raw_source():
    _, _, source, selection, findings, response = fixture()
    original = deepcopy((source, selection, response))
    draft = apply_meaning_resolution(selection, response, findings, source)
    assert draft.decisions[0].required_meanings == selection.decisions[0].required_meanings[:3]
    assert draft.decisions[1] == selection.decisions[1]
    assert (source, selection, response) == original


@pytest.mark.parametrize('fault', ['unknown', 'protected', 'non_atomic', 'duplicate', 'self',
    'foreign', 'unknown_keeper', 'repeated_keeper', 'edit_target', 'edit_keeper', 'missing_ref',
    'wrong_classification', 'wrong_action', 'empty_reason', 'second_defect', 'chain'])
def test_merge_cannot_delete_protected_or_unowned_meaning(fault):
    _, _, source, selection, findings, response = fixture()
    merge, disposition = response.merges[0], response.finding_dispositions[0]
    if fault == 'unknown': merge.meaning_id = 'unknown'
    elif fault == 'protected': merge.meaning_id = 'part-0:meaning-1'
    elif fault == 'non_atomic': findings[0]['issue_type'] = 'missing_qualification'
    elif fault == 'duplicate': response.merges *= 2
    elif fault == 'self': merge.retained_meaning_ids = [merge.meaning_id]
    elif fault == 'foreign':
        selection.decisions[1].include = True
        selection.decisions[1].required_meanings = [deepcopy(selection.decisions[0].required_meanings[1])]
        merge.retained_meaning_ids = ['part-1:meaning-1']
    elif fault == 'unknown_keeper': merge.retained_meaning_ids = ['part-0:meaning-999']
    elif fault == 'repeated_keeper': merge.retained_meaning_ids *= 2
    elif fault in {'edit_target', 'edit_keeper'}:
        response.edits = [MeaningResolutionEdit(
            meaning_id=merge.meaning_id if fault == 'edit_target' else 'part-0:meaning-2',
            required_meanings=[dict(meaning=selection.decisions[0].required_meanings[
                3 if fault == 'edit_target' else 1].meaning)])]
    elif fault == 'missing_ref': disposition.referenced_meaning_ids = [merge.meaning_id]
    elif fault == 'wrong_classification': disposition.classification = 'missing_qualification'
    elif fault == 'wrong_action': disposition.action = 'already_covered'
    elif fault == 'empty_reason': merge.reason = ' '
    elif fault == 'second_defect':
        findings.append(dict(findings[0], finding_id='finding-1', issue_type='unsupported_assertion'))
        response.finding_dispositions.append(disposition.model_copy(update={'finding_id': 'finding-1'}))
    else:
        response.merges.append(merge.model_copy(update={'meaning_id': 'part-0:meaning-2',
            'retained_meaning_ids': ['part-0:meaning-4']}))
    before = deepcopy(selection)
    with pytest.raises(ValueError):
        apply_meaning_resolution(selection, response, findings, source)
    assert selection == before


def test_claimed_deletion_gets_one_concrete_merge_feedback_and_preserves_other_edit():
    values = fixture()
    _, reading, source, selection, findings, response = values
    findings.append(dict(finding_id='finding-1', kind='meaning', issue_type='missing_qualification',
        part_id='part-0', meaning_id='part-0:meaning-1',
        current_meaning=selection.decisions[0].required_meanings[0].meaning,
        source_quote=source['parts'][0]['source_text'], reason='Preserve the delivery prerequisite.'))
    response.edits = [MeaningResolutionEdit(meaning_id='part-0:meaning-1', required_meanings=[dict(
        meaning='The system schedules appointments with staff training required before delivery.')])]
    response.finding_dispositions.append(response.finding_dispositions[0].model_copy(update={
        'finding_id': 'finding-1', 'classification': 'missing_qualification',
        'referenced_meaning_ids': ['part-0:meaning-1'], 'reason': 'Preserve the source condition.'}))
    rejected = response.model_copy(deep=True)
    rejected.merges = []
    rejected.finding_dispositions[0].referenced_meaning_ids = ['part-0:meaning-4']
    rejected.finding_dispositions[0].reason = 'The duplicate is removed.'
    client = Replies(rejected, response)
    draft, ledger = resolve(client, values)
    assert len(client.messages) == 2
    assert 'use merges' in client.messages[1][-1]['content']
    assert len(draft.decisions[0].required_meanings) == 3
    assert draft.decisions[0].required_meanings[0] == response.edits[0].required_meanings[0]
    assert ledger['merges'] == [m.model_dump(mode='json') for m in response.merges]
    assert ledger['semantic_approval'] is False and not reading.audience_selection
    audit = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert audit['protocol_attempts'][0]['response'] == rejected.model_dump(mode='json')


def test_repeated_claimed_deletion_still_fails_in_two_calls():
    values = fixture()
    rejected = values[-1].model_copy(deep=True)
    rejected.merges = []
    client = Replies(rejected, rejected)
    with pytest.raises(UnappliedMeaningCorrection):
        resolve(client, values)
    assert len(client.messages) == 2


@pytest.mark.parametrize('accepted', [True, False])
def test_structurally_valid_merge_still_needs_independent_full_source_review(accepted):
    values = fixture()
    _, reading, source, selection, _, response = values
    draft, ledger = resolve(Replies(response), values)
    class Reviewer:
        def generate_structured(self, messages, schema, **kwargs):
            payload = review_payload(messages)
            assert payload['source'] == source
            assert len(payload['current_meanings']) == 3
            assert len(payload['meaning_resolution']['before_resolution_meanings']) == 4
            assert payload['meaning_resolution']['merges'] == ledger['merges']
            assert 'Reject any lost unique meaning' in messages[0]['content']
            return review_response(schema, messages, accepted=accepted, repair_scope='meanings',
                reason='Independent synthetic union-preservation verdict.')
    verdict = review_current_selection(Reviewer(), source, draft.model_dump(mode='json')['decisions'],
        'Review all owned evidence.', reading, attempt=2,
        meaning_revision_base=selection.model_dump(mode='json')['decisions'], inventory_revision_base=None,
        binding_budget={'used': False}, meaning_resolution=ledger)
    assert verdict.accepted is accepted
    assert not reading.audience_selection


@pytest.mark.parametrize('accepted', [True, False])
def test_complete_introduction_flow_never_treats_merge_as_approval(accepted):
    result, reading, source, selection, _, _ = fixture()
    selection.decisions[0].required_meanings = [RequiredMeaning(meaning=text) for text in (
        'The system schedules appointments and staff training is required before delivery.',
        'Staff training is required before delivery.', 'Inspections limit capacity.')]
    operations, reviews = [], []
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            operations.append(schema.__name__)
            if schema.__name__ == 'IntroductionAudienceSelection':
                return selection.model_copy(deep=True)
            if schema.__name__ == 'IntroductionMeaningRevision':
                return schema(edits=[dict(meaning_id='meaning-0', required_meanings=[dict(
                    meaning='The system schedules appointments.'), dict(
                    meaning='Before delivery, staff training is required.')]),
                    dict(meaning_id='meaning-1', required_meanings=[dict(
                        meaning='Staff training is required before delivery.')]),
                    dict(meaning_id='meaning-2', required_meanings=[dict(
                        meaning='Inspections limit capacity.')])])
            if schema.__name__ == 'IntroductionMeaningResolution':
                return schema(merges=[dict(meaning_id='part-0:meaning-2',
                    retained_meaning_ids=['part-0:meaning-3'], reason='Same source-owned training prerequisite.')],
                    finding_dispositions=[dict(finding_id='finding-0', classification='atomicity', action='corrected',
                        referenced_meaning_ids=['part-0:meaning-2', 'part-0:meaning-3'],
                        reason='The surviving original assertion retains the complete prerequisite.')])
            payload = review_payload(messages)
            reviews.append(payload)
            if len(reviews) == 3:
                assert len(payload['current_meanings']) == 3
                assert len(payload['meaning_resolution']['before_resolution_meanings']) == 4
                assert payload['meaning_resolution']['merges'][0]['retained_meaning_ids'] == ['part-0:meaning-3']
                assert payload['current_meanings'][1]['meaning_id'] == 'part-0:meaning-2'
                assert payload['current_meanings'][1]['meaning'] == 'Staff training is required before delivery.'
                return review_response(schema, messages, accepted=accepted, repair_scope='meanings',
                    reason='Independent synthetic judgment; protocol consolidation alone proves nothing.')
            target = payload['current_meanings'][0 if len(reviews) == 1 else 1]
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='Split the compound assertion.' if len(reviews) == 1 else 'Consolidate same-part duplication.',
                findings=[dict(kind='meaning', issue_type='atomicity', part_id=target['part_id'],
                    meaning_id=target['meaning_id'], current_meaning=target['meaning'],
                    source_quote=source['parts'][0]['source_text'], reason='Source-owned atomicity finding.')])
    if accepted:
        select_introduction_audience(Client(), result, reading)
        assert reading.audience_selection['independent_review']['accepted']
    else:
        with pytest.raises(ValueError, match='not independently accepted'):
            select_introduction_audience(Client(), result, reading)
        assert not reading.audience_selection and reading.audience_part_ids is None
    assert operations == ['IntroductionAudienceSelection', 'IntroductionAudienceReview',
        'IntroductionMeaningRevision', 'IntroductionAudienceReview',
        'IntroductionMeaningResolution', 'IntroductionAudienceReview']
