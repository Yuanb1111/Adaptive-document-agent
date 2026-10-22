"""A single bounded mixed correction owns all findings without semantic approval."""
from copy import deepcopy
from concurrent.futures import CancelledError

import pytest

from adaptive_document_agent.agent.introduction_audience import IntroductionAudienceSelection
from adaptive_document_agent.agent.introduction_audience_review import IntroductionAudienceReview
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    IntroductionMeaningResolution, apply_meaning_resolution, finding_inventory, resolve_meaning_findings)
from adaptive_document_agent.services.llm.exceptions import LLMTransportError, PrivacyViolationError
from tests.test_compact_summary_v111 import fixture
from tests.introduction_review_helpers import review_payload, review_response


def mixed_fixture():
    _, review, _ = fixture(4)
    texts = ['The system schedules appointments only after staff training. Inspections limit capacity. '
             'The service operates on weekdays.',
             'Mandatory inspections can suspend service.', 'The system retains delivery records.',
             'A pilot ran in 2019.']
    for part, text in zip(review.parts, texts):
        part.source_text = text
    selection = IntroductionAudienceSelection(decisions=[dict(part_id=part.id,
        include=index in {0, 2}, reason='Core scope.' if index in {0, 2} else 'Later context.',
        required_meanings=[dict(meaning=m, source_quote=texts[index]) for m in (
            ['The system schedules appointments.', 'Inspections limit capacity.'] if index == 0 else
            ['The system retains delivery records.'] if index == 2 else [])])
        for index, part in enumerate(review.parts)])
    source = dict(parts=[part.model_dump(exclude={'facts'}) for part in review.parts])
    verdict = IntroductionAudienceReview(accepted=False, reason='Resolve all current defects.',
        repair_scope='selection', findings=[dict(kind='meaning', issue_type='missing_qualification',
            part_id='part-0', meaning_id='part-0:meaning-1', current_meaning='The system schedules appointments.',
            source_quote=texts[0].split('.')[0]+'.', reason='Training is a necessary condition.'),
            dict(kind='included_part', issue_type='new_assertion', part_id='part-0',
                 source_quote='The service operates on weekdays.', reason='Service scope is essential.'),
            dict(kind='omitted_part', issue_type='new_assertion', part_id='part-1',
                 source_quote=texts[1], reason='Service suspension is essential.')])
    response = IntroductionMeaningResolution(edits=[dict(meaning_id='part-0:meaning-1',
        required_meanings=[dict(meaning=texts[0].split('.')[0]+'.')])],
        additions=[dict(part_id='part-0', required_meanings=[dict(meaning='The service operates on weekdays.')])],
        inclusions=[dict(part_id='part-1', include=True, reason='Essential availability condition.',
                         required_meanings=[dict(meaning=texts[1])])], finding_dispositions=[
            dict(finding_id=f'finding-{index}', classification='missing_qualification' if index == 0 else 'new_assertion',
                 action='corrected', referenced_meaning_ids=['part-0:meaning-1'] if index == 0 else [],
                 source_quote=verdict.findings[index].source_quote, reason='Correct this exact owned defect.')
            for index in range(3)])
    return review, source, selection, verdict, response


def test_mixed_correction_preserves_unaffected_meanings_decisions_reasons_and_source():
    _, source, selection, verdict, response = mixed_fixture()
    before, evidence = deepcopy(selection), deepcopy(source)
    updated = apply_meaning_resolution(selection, response, finding_inventory(verdict), source)
    assert updated.decisions[0].required_meanings[1] == before.decisions[0].required_meanings[1]
    assert updated.decisions[0].reason == before.decisions[0].reason
    assert updated.decisions[2:] == before.decisions[2:]
    assert updated.decisions[1].include and updated.decisions[1].reason == response.inclusions[0].reason
    assert len(updated.decisions[0].required_meanings) == 3
    assert selection == before and source == evidence


@pytest.mark.parametrize('fault', ['unknown_part', 'duplicate_part', 'already_included', 'unidentified_part',
    'blank_reason', 'false_include', 'empty_inclusion', 'missing_inclusion', 'omission_as_addition',
    'unaffected_meaning', 'cross_part_meaning', 'duplicate_edit', 'missing_finding', 'duplicate_finding',
    'unknown_finding', 'foreign_quote', 'cross_part_ref', 'unaddressed_inclusion'])
def test_mixed_protocol_rejects_unowned_incomplete_or_implicit_edits(fault):
    _, source, selection, verdict, response = mixed_fixture()
    if fault == 'unknown_part': response.inclusions[0].part_id = 'unknown'
    elif fault == 'duplicate_part': response.inclusions.append(response.inclusions[0].model_copy(deep=True))
    elif fault == 'already_included': response.inclusions[0].part_id = 'part-0'
    elif fault == 'unidentified_part': response.inclusions[0].part_id = 'part-3'
    elif fault == 'blank_reason': response.inclusions[0].reason = ' '
    elif fault == 'false_include': response.inclusions[0].include = False
    elif fault == 'empty_inclusion': response.inclusions[0].required_meanings.clear()
    elif fault == 'missing_inclusion': response.inclusions.clear()
    elif fault == 'omission_as_addition': response.inclusions.clear(); response.additions[0].part_id = 'part-1'
    elif fault == 'unaffected_meaning': response.edits[0].meaning_id = 'part-0:meaning-2'
    elif fault == 'cross_part_meaning': response.edits[0].meaning_id = 'part-2:meaning-1'
    elif fault == 'duplicate_edit': response.edits.append(response.edits[0].model_copy(deep=True))
    elif fault == 'missing_finding': response.finding_dispositions.pop()
    elif fault == 'duplicate_finding': response.finding_dispositions.append(response.finding_dispositions[0].model_copy())
    elif fault == 'unknown_finding': response.finding_dispositions[0].finding_id = 'another-finding'
    elif fault == 'foreign_quote': response.finding_dispositions[2].source_quote = 'A pilot ran in 2019.'
    elif fault == 'cross_part_ref': response.finding_dispositions[2].referenced_meaning_ids = ['part-0:meaning-1']
    else: response.finding_dispositions[2].action = 'outside_selected_scope'
    with pytest.raises(ValueError):
        apply_meaning_resolution(selection, response, finding_inventory(verdict), source)


@pytest.mark.parametrize('field', ['include', 'reason', 'required_meanings'])
def test_new_inclusion_requires_explicit_model_selection_and_nonempty_authorship(field):
    *_, response = mixed_fixture()
    wire = response.model_dump()
    wire['inclusions'][0].pop(field)
    with pytest.raises(ValueError):
        IntroductionMeaningResolution.model_validate(wire)


@pytest.mark.parametrize('error', [LLMTransportError('transport unavailable'),
    PrivacyViolationError('private mode blocked request'), CancelledError('cancelled')])
def test_mixed_resolution_propagates_operational_failures_with_no_approval(error):
    review, source, selection, verdict, _ = mixed_fixture()
    class Gateway:
        calls = 0
        def generate_structured(self, *args, **kwargs):
            self.calls += 1
            raise error
    gateway = Gateway()
    with pytest.raises(type(error)):
        resolve_meaning_findings(gateway, source, selection, selection.model_dump()['decisions'],
                                 verdict, review)
    assert gateway.calls == 1
    record = review.plan_audits[-1]['introduction_meaning_resolution']
    assert record['status'] in {'failed', 'cancelled'} and 'semantic_approval' not in record


def test_response_cannot_implicitly_replace_protected_decisions():
    *_, response = mixed_fixture()
    wire = response.model_dump()
    wire['decisions'] = []
    with pytest.raises(ValueError):
        IntroductionMeaningResolution.model_validate(wire)


@pytest.mark.parametrize('final_acceptance', [True, False])
@pytest.mark.parametrize('mirrored_inclusion', [False, True])
def test_first_review_mixed_findings_use_targeted_repair_and_still_require_fresh_acceptance(final_acceptance, mirrored_inclusion):
    result, _, _ = fixture(4)
    reading, _, selection, rejected, response = mixed_fixture()
    calls, reviews = [], []

    class Gateway:
        resolutions = 0
        def generate_structured(self, messages, schema, **kwargs):
            calls.append(schema.__name__)
            if schema.__name__ == 'IntroductionAudienceSelection':
                return schema.model_validate(selection.model_dump())
            payload = review_payload(messages)
            if schema.__name__ == 'IntroductionMeaningResolution':
                self.resolutions += 1
                if self.resolutions == 1:
                    assert payload['eligible_inclusions'] == [dict(part_id='part-1', current_reason='Later context.')]
                    authored = response.model_copy(deep=True)
                    if mirrored_inclusion:
                        from adaptive_document_agent.agent.introduction_meaning_resolution import MeaningResolutionAddition
                        inclusion = authored.inclusions[0]
                        authored.additions.append(MeaningResolutionAddition(part_id=inclusion.part_id,
                            required_meanings=deepcopy(inclusion.required_meanings)))
                    if not final_acceptance:
                        authored.edits[0].required_meanings[0].meaning = 'The system schedules appointments efficiently.'
                    return schema.model_validate(authored.model_dump())
                assert not payload['eligible_inclusions']
                return schema(edits=[dict(meaning_id='part-0:meaning-1', required_meanings=[dict(
                    meaning='The system schedules appointments on demand.')])], finding_dispositions=[dict(
                    finding_id='finding-0', classification='missing_qualification', action='corrected',
                    referenced_meaning_ids=['part-0:meaning-1'], source_quote=rejected.findings[0].source_quote,
                    reason='The source reviewer must judge this newly authored correction.')])
            assert schema.__name__ == 'IntroductionAudienceReview'
            reviews.append(deepcopy(payload))
            if len(reviews) == 1:
                return review_response(schema, messages, accepted=False, repair_scope='selection',
                    reason='Mixed source defects.', findings=[f.model_dump() for f in rejected.findings])
            assert payload['meaning_resolution']['semantic_approval'] is False
            assert payload['decisions'][2:] == reviews[0]['decisions'][2:]
            assert payload['decisions'][0]['required_meanings'][1] == reviews[0]['decisions'][0]['required_meanings'][1]
            assert payload['decisions'][1]['include']
            if final_acceptance:
                return review_response(schema, messages, accepted=True, reason='Fresh complete source judgment.')
            current = payload['current_meanings'][0]
            finding = {**rejected.findings[0].model_dump(),
                       'current_meaning': current['meaning'], 'meaning_id': current['meaning_id']}
            return review_response(schema, messages, accepted=False, repair_scope='meanings',
                reason='The authored copy still omits the source training condition.', findings=[finding])

    from adaptive_document_agent.agent.introduction_audience import select_introduction_audience
    if final_acceptance:
        select_introduction_audience(Gateway(), result, reading)
        assert reading.audience_selection['independent_review']['accepted']
        assert len(reviews) == 2 and calls.count('IntroductionMeaningResolution') == 1
    else:
        with pytest.raises(ValueError, match='not independently accepted'):
            select_introduction_audience(Gateway(), result, reading)
        assert reading.audience_part_ids is None and not reading.audience_selection
        assert len(reviews) == 3 and calls.count('IntroductionMeaningResolution') == 2
    assert calls.count('IntroductionAudienceSelection') == 1
    assert 'IntroductionAudienceSelectionAddition' not in calls and 'IntroductionMeaningRevision' not in calls
