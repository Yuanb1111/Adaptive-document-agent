"""An unchanged protected assertion plus new copy is an owned addition, not an edit."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience_review import (
    IntroductionAudienceReview, review_current_selection)
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    MeaningResolutionAddition, MeaningResolutionEdit, apply_meaning_resolution, resolve_meaning_findings)
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_introduction_disposition_evidence_v153 import ResolutionGateway
from tests.test_introduction_meaning_resolution_v147 import resolution_fixture


def fixture():
    _, reading, source, selection, findings, response = resolution_fixture()
    # A new independent detail in the already selected source part. Its current
    # assertions remain protected; the reviewer authorizes additions only.
    source['parts'][0]['source_text'] += ' The service supports remote appointments and local appointments.'
    reading.parts[0].source_text = source['parts'][0]['source_text']
    findings[0].update(kind='included_part', meaning_id='', current_meaning='',
        source_quote='The service supports remote appointments and local appointments.',
        reason='The source-defined service channels are absent from the selected union.')
    response.edits = [MeaningResolutionEdit(meaning_id='part-0:meaning-1', required_meanings=[
        dict(meaning=selection.decisions[0].required_meanings[0].meaning),
        dict(meaning='The service supports remote appointments.'),
        dict(meaning='The service supports local appointments.')])]
    response.finding_dispositions[0].classification = 'missing_qualification'
    response.finding_dispositions[0].action = 'corrected'
    response.finding_dispositions[0].referenced_meaning_ids = ['part-0:meaning-1']
    response.finding_dispositions[0].source_quote = source['parts'][0]['source_text']
    return reading, source, selection, findings, response


@pytest.mark.parametrize('original_quote', [False, True])
def test_append_transport_equals_explicit_addition_and_preserves_every_original(original_quote):
    _, source, selection, findings, response = fixture()
    if original_quote:
        response.edits[0].required_meanings[0].source_quote = selection.decisions[0].required_meanings[0].source_quote
    canonical = response.model_copy(deep=True)
    canonical.additions = [MeaningResolutionAddition(part_id='part-0',
        required_meanings=canonical.edits[0].required_meanings[1:])]
    canonical.edits = []
    before = deepcopy((source, selection, findings, response))
    audit = {}
    actual = apply_meaning_resolution(selection, response, findings, source, transport_audit=audit)
    assert actual == apply_meaning_resolution(selection, canonical, findings, source)
    old = selection.decisions[0].required_meanings
    assert actual.decisions[0].required_meanings[:len(old)] == old
    assert actual.decisions[0].required_meanings[len(old):] == response.edits[0].required_meanings[1:]
    assert actual.decisions[1:] == selection.decisions[1:]
    assert audit['append_only_edits'] == [dict(meaning_id='part-0:meaning-1', part_id='part-0',
                                             appended_count=2, original_meaning_preserved=True)]
    assert (source, selection, findings, response) == before


@pytest.mark.parametrize('fault', ['rewrite', 'whitespace', 'foreign_quote', 'unknown_id',
    'duplicate_id', 'foreign_part', 'no_part_finding', 'repeat_original', 'mixed_additions',
    'missing_disposition', 'not_corrected'])
def test_append_transport_cannot_authorize_a_rewrite_or_cross_part_addition(fault):
    _, source, selection, findings, response = fixture()
    edit = response.edits[0]
    if fault == 'rewrite': edit.required_meanings[0].meaning += ' Always.'
    elif fault == 'whitespace': edit.required_meanings[0].meaning += ' '
    elif fault == 'foreign_quote': edit.required_meanings[0].source_quote = 'Another source.'
    elif fault == 'unknown_id': edit.meaning_id = 'part-0:meaning-99'
    elif fault == 'duplicate_id': response.edits.append(deepcopy(edit))
    elif fault == 'foreign_part':
        selection.decisions[1].include = True
        selection.decisions[1].required_meanings = deepcopy(selection.decisions[0].required_meanings)
        edit.meaning_id = 'part-1:meaning-1'
    elif fault == 'no_part_finding':
        findings[0].update(kind='meaning', meaning_id='part-0:meaning-2',
                           current_meaning=selection.decisions[0].required_meanings[1].meaning)
    elif fault == 'repeat_original': edit.required_meanings.append(deepcopy(edit.required_meanings[0]))
    elif fault == 'mixed_additions': response.additions = [MeaningResolutionAddition(
        part_id='part-0', required_meanings=edit.required_meanings[1:])]
    elif fault == 'missing_disposition': response.finding_dispositions.clear()
    else:
        response.finding_dispositions[0].action = 'already_covered'
        response.finding_dispositions[0].classification = 'already_covered'
    before = deepcopy((selection, response, source))
    audit = {}
    with pytest.raises(ValueError):
        apply_meaning_resolution(selection, response, findings, source, transport_audit=audit)
    assert not audit and (selection, response, source) == before


@pytest.mark.parametrize('accepted', [False, True])
def test_raw_append_and_source_ownership_reach_fresh_independent_review(accepted):
    reading, source, selection, findings, response = fixture()
    verdict = IntroductionAudienceReview(accepted=False, repair_scope='meanings', reason='Missing source context.',
        findings=[{k: v for k, v in finding.items() if k != 'finding_id'} for finding in findings])
    client = ResolutionGateway(response)
    draft, ledger = resolve_meaning_findings(client, source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading)
    record = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert record['response'] == response.model_dump(mode='json')
    assert len(client.messages) == 1 and record['status'] == 'protocol_validated'
    assert ledger['append_only_edits'] == record['append_only_edits']
    assert ledger['semantic_approval'] is record['semantic_approval'] is False

    class Reviewer:
        def generate_structured(self, messages, schema, **kwargs):
            assert 'remote appointments' in messages[-1]['content']
            assert 'local appointments' in messages[-1]['content']
            return review_response(schema, messages, accepted=accepted, repair_scope='meanings',
                                   reason='Independently assess complete source and revised union.')

    reviewed = review_current_selection(Reviewer(), source, draft.model_dump(mode='json')['decisions'],
        'Independently review full source.', reading, attempt=2,
        meaning_revision_base=selection.model_dump(mode='json')['decisions'],
        inventory_revision_base=None, binding_budget={'used': False}, meaning_resolution=ledger)
    assert reviewed.accepted is accepted
    assert not reading.audience_selection and reading.audience_part_ids is None


@pytest.mark.parametrize('accepted', [False, True])
def test_full_selection_flow_requires_independent_acceptance_after_append(accepted):
    from adaptive_document_agent.agent.introduction_audience import select_introduction_audience

    result, *_ = resolution_fixture()
    reading, _, selection, findings, proposal = fixture()
    operations = []
    reviews = []

    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            operations.append(schema.__name__)
            if schema.__name__ == 'IntroductionAudienceSelection':
                value = selection.model_dump()
                value['decisions'][0]['required_meanings'] = [dict(
                    meaning='The system schedules appointments and requires staff training before delivery.')]
                return schema.model_validate(value)
            if schema.__name__ == 'IntroductionMeaningRevision':
                return schema(edits=[dict(meaning_id='meaning-0', required_meanings=[dict(
                    meaning='The system schedules appointments.'), dict(meaning='Staff training is required before delivery.')])])
            if schema.__name__ == 'IntroductionMeaningResolution':
                return schema.model_validate(proposal.model_dump())
            payload = review_payload(messages)
            reviews.append(payload)
            if len(reviews) == 3:
                current = [m['meaning'] for m in payload['current_meanings']]
                assert current == ['The system schedules appointments.', 'Staff training is required before delivery.',
                                   'The service supports remote appointments.', 'The service supports local appointments.']
                assert payload['meaning_resolution']['append_only_edits'][0]['appended_count'] == 2
                return review_response(schema, messages, accepted=accepted, repair_scope='meanings',
                                       reason='Fresh independent judgment of the full revised source union.')
            if len(reviews) == 1:
                target = payload['current_meanings'][0]
                finding = dict(kind='meaning', issue_type='atomicity', part_id=target['part_id'],
                    meaning_id=target['meaning_id'], current_meaning=target['meaning'],
                    source_quote='Staff training is required before delivery.', reason='Separate the assertions.')
            else:
                finding = {k: v for k, v in findings[0].items() if k != 'finding_id'}
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                                   reason=finding['reason'], findings=[finding])

    if accepted:
        select_introduction_audience(Client(), result, reading)
        assert reading.audience_selection['independent_review']['accepted']
    else:
        with pytest.raises(ValueError, match='not independently accepted'):
            select_introduction_audience(Client(), result, reading)
        assert not reading.audience_selection
    assert operations == ['IntroductionAudienceSelection', 'IntroductionAudienceReview', 'IntroductionMeaningRevision',
                          'IntroductionAudienceReview', 'IntroductionMeaningResolution', 'IntroductionAudienceReview']
