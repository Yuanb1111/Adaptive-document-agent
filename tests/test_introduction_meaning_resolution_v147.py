"""A final finding ledger resolves union mistakes without granting acceptance."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_audience import IntroductionAudienceSelection, select_introduction_audience
from adaptive_document_agent.agent.introduction_audience_review import (
    IntroductionAudienceReview, current_meanings, selection_wire, review_current_selection)
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    IntroductionMeaningResolution, apply_meaning_resolution, finding_inventory, resolve_meaning_findings,
    MeaningResolutionEdit,
)
from tests.introduction_review_helpers import review_payload, review_response
from tests.test_compact_summary_v111 import fixture


def resolution_fixture():
    result, reading, _ = fixture(2)
    text = ('The system schedules appointments. Staff training is required before delivery. '
            'Inspections limit capacity. A historical pilot ran in 2019.')
    reading.parts[0].source_text = text
    selection = IntroductionAudienceSelection(decisions=[dict(part_id=part.id,
        include=index == 0, reason='Core scheduling and delivery conditions.' if not index else 'Redundant context.',
        required_meanings=[dict(meaning=value, source_quote=text) for value in (
            'The system schedules appointments.', 'Staff training is required before delivery.',
            'Inspections limit capacity.')] if not index else []) for index, part in enumerate(reading.parts)])
    values = selection.model_dump(mode='json')['decisions']
    source = dict(parts=[part.model_dump(exclude={'facts'}) for part in reading.parts])
    finding = dict(kind='meaning', issue_type='missing_qualification', part_id='part-0',
        meaning_id='part-0:meaning-1', current_meaning=values[0]['required_meanings'][0]['meaning'],
        source_quote='Staff training is required before delivery.', reason='Training is missing from the scheduling assertion.')
    verdict = IntroductionAudienceReview(accepted=False, reason='A condition is missing.',
        repair_scope='meanings', findings=[finding])
    response = IntroductionMeaningResolution(finding_dispositions=[dict(finding_id='finding-0',
        classification='already_covered', action='already_covered', referenced_meaning_ids=['part-0:meaning-2'],
        source_quote=finding['source_quote'], reason='The separate current training assertion expresses this condition.')])
    return result, reading, source, selection, finding_inventory(verdict), response


def test_complete_noop_ledger_preserves_all_current_copy_and_does_not_approve_it():
    _, _, source, selection, findings, response = resolution_fixture()
    before = deepcopy(selection)
    assert apply_meaning_resolution(selection, response, findings, source) == selection == before


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'unknown_finding', 'unknown_meaning',
    'foreign_quote', 'qualifier_outside_scope', 'false_corrected', 'unaddressed_edit', 'omitted_part'])
def test_invalid_finding_ledgers_cannot_authorize_a_noop_or_arbitrary_patch(fault):
    _, _, source, selection, findings, response = resolution_fixture()
    row = response.finding_dispositions[0]
    if fault == 'missing': response.finding_dispositions.clear()
    elif fault == 'duplicate': response.finding_dispositions.append(row.model_copy())
    elif fault == 'unknown_finding': row.finding_id = 'another-finding'
    elif fault == 'unknown_meaning': row.referenced_meaning_ids = ['part-1:meaning-1']
    elif fault == 'foreign_quote': row.source_quote = 'Unsupported source sentence.'
    elif fault == 'qualifier_outside_scope': row.action, row.classification = 'outside_selected_scope', 'missing_qualification'
    elif fault == 'false_corrected': row.action, row.classification = 'corrected', 'missing_qualification'
    elif fault == 'omitted_part': findings[0]['part_id'] = 'part-1'
    else: response.edits = [MeaningResolutionEdit(meaning_id='part-0:meaning-1',
        required_meanings=[dict(meaning='Changed claim.')])]
    with pytest.raises(ValueError):
        apply_meaning_resolution(selection, response, findings, source)


def test_targeted_atomic_split_retains_qualifiers_and_protects_other_copy():
    _, _, source, selection, findings, _ = resolution_fixture()
    old = deepcopy(selection)
    response = IntroductionMeaningResolution(edits=[dict(meaning_id='part-0:meaning-1',
        required_meanings=[dict(meaning='The system schedules appointments for delivery.')])],
        finding_dispositions=[dict(finding_id='finding-0', classification='atomicity', action='corrected',
            referenced_meaning_ids=['part-0:meaning-1'], source_quote=source['parts'][0]['source_text'],
            reason='Revised this exact assertion; the independent source review must judge it.')])
    revised = apply_meaning_resolution(selection, response, findings, source)
    assert revised.decisions[1] == old.decisions[1]
    assert revised.decisions[0].required_meanings[1:] == old.decisions[0].required_meanings[1:]


@pytest.mark.parametrize('final_acceptance', [True, False])
def test_only_final_fresh_full_source_review_can_accept_a_union_disposition(final_acceptance):
    result, reading, source, selection, _, _ = resolution_fixture()
    calls, reviews = [], []
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            payload = review_payload(messages)
            if schema.__name__ == 'IntroductionAudienceSelection':
                value = selection.model_dump()
                value['decisions'][0]['required_meanings'] = [dict(
                    meaning='The system schedules appointments and requires staff training before delivery.')]
                return schema.model_validate(value)
            if schema.__name__ == 'IntroductionMeaningRevision':
                return schema(edits=[dict(meaning_id='meaning-0', required_meanings=[dict(
                    meaning='The system schedules appointments.'), dict(meaning='Staff training is required before delivery.')])])
            if schema.__name__ == 'IntroductionMeaningResolution':
                return schema(finding_dispositions=[dict(finding_id='finding-0', classification='already_covered',
                    action='already_covered', referenced_meaning_ids=['part-0:meaning-2'],
                    source_quote='Staff training is required before delivery.',
                    reason='The complete current union already includes this condition.')])
            reviews.append(payload)
            assert payload['source']['parts'][0]['source_text'] == source['parts'][0]['source_text']
            if len(reviews) == 3:
                assert payload['meaning_resolution']['finding_dispositions'][0]['action'] == 'already_covered'
                assert len(payload['current_meaning_unions'][0]['meaning_ids']) == 2
                return review_response(schema, messages, accepted=final_acceptance,
                    repair_scope='meanings', reason='Final independent source judgment.')
            target = payload['current_meanings'][0]
            finding = dict(kind='meaning', issue_type='atomicity' if len(reviews) == 1 else 'missing_qualification',
                part_id=target['part_id'], meaning_id=target['meaning_id'], current_meaning=target['meaning'],
                source_quote='Staff training is required before delivery.', reason='Split atomic claims.'
                if len(reviews) == 1 else 'The training assertion must be considered across the current union.')
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason=finding['reason'], findings=[finding])
    if final_acceptance:
        select_introduction_audience(Client(), result, reading)
        assert reading.audience_selection['independent_review']['accepted']
    else:
        with pytest.raises(ValueError, match='not independently accepted'):
            select_introduction_audience(Client(), result, reading)
        assert not reading.audience_selection and reading.audience_part_ids is None
    assert calls == ['IntroductionAudienceSelection', 'IntroductionAudienceReview', 'IntroductionMeaningRevision',
                     'IntroductionAudienceReview', 'IntroductionMeaningResolution', 'IntroductionAudienceReview']
    assert len(reviews) == 3


def test_review_wire_deduplicates_evidence_without_mutating_canonical_values():
    _, _, source, selection, _, _ = resolution_fixture()
    values = selection.model_dump(mode='json')['decisions']
    original = deepcopy(values)
    wire = selection_wire(values)
    assert values == original
    assert all('source_quote' not in meaning for decision in wire for meaning in decision['required_meanings'])
    assert [meaning['meaning'] for decision in wire for meaning in decision['required_meanings']] == [
        row['meaning'] for row in current_meanings(values)]
    assert source['parts'][0]['source_text'] == values[0]['required_meanings'][0]['source_quote']


def test_split_keeps_disposition_ids_in_an_explicit_before_namespace():
    _, reading, source, selection, _, _ = resolution_fixture()
    selection.decisions[0].required_meanings = selection.decisions[0].required_meanings[:2]
    selection.decisions[0].required_meanings[0].meaning += ' Inspections limit capacity.'
    values = selection.model_dump(mode='json')['decisions']
    before = current_meanings(values)
    findings = [dict(kind='meaning', part_id='part-0', meaning_id='part-0:meaning-1',
        current_meaning=before[0]['meaning'], source_quote=source['parts'][0]['source_text'],
        reason=reason) for reason in ('Separate atomic assertions.', 'Training is supposedly absent.')]
    rejected = IntroductionAudienceReview(accepted=False, repair_scope='meanings',
        reason='Resolve these two findings.', findings=findings)
    class Client:
        def generate_structured(self, messages, schema, **kwargs):
            if schema.__name__ == 'IntroductionMeaningResolution':
                return schema(edits=[dict(meaning_id='part-0:meaning-1', required_meanings=[dict(
                    meaning='The system schedules appointments.'), dict(meaning='Inspections limit capacity.')])],
                    finding_dispositions=[dict(finding_id='finding-0', classification='atomicity', action='corrected',
                        referenced_meaning_ids=['part-0:meaning-1'], source_quote=source['parts'][0]['source_text'], reason='Split both assertions.'),
                        dict(finding_id='finding-1', classification='already_covered', action='already_covered',
                        referenced_meaning_ids=['part-0:meaning-2'], source_quote='Staff training is required before delivery.',
                        reason='The immutable second meaning already states training.')])
            payload = json.loads(messages[-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
            resolution = payload['historical_context']['meaning_resolution']
            assert resolution['reference_namespace'] == 'before_resolution_meanings'
            historical = {row['meaning_id']: row['meaning'] for row in resolution['before_resolution_meanings']}
            current = {row['meaning_id']: row['meaning'] for row in payload['current_meanings']}
            assert historical['part-0:meaning-2'] == 'Staff training is required before delivery.'
            assert current['part-0:meaning-2'] == 'Inspections limit capacity.'
            assert current['part-0:meaning-3'] == historical['part-0:meaning-2']
            assert all('source_quote' not in row for row in resolution['before_resolution_meanings'])
            return review_response(schema, messages, accepted=True, reason='Synthetic source review resolves both namespaces.')
    client = Client()
    revised, ledger = resolve_meaning_findings(client, source, selection, values, rejected, reading)
    canonical = revised.model_dump(mode='json')['decisions']
    for decision in canonical:
        for meaning in decision['required_meanings']:
            meaning['source_quote'] = source['parts'][0]['source_text']
    assert review_current_selection(client, source, canonical, 'Review complete source.', reading,
        attempt=2, meaning_revision_base=values, inventory_revision_base=None,
        binding_budget={'used': False}, meaning_resolution=ledger).accepted
