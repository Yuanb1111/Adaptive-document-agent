"""Protected assertions echoed verbatim survive without granting edit authority."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_audience import RequiredMeaning
from adaptive_document_agent.agent.introduction_audience_review import IntroductionAudienceReview
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    MeaningResolutionEdit, apply_meaning_resolution, resolve_meaning_findings)
from tests.test_introduction_disposition_evidence_v153 import ResolutionGateway
from tests.test_introduction_meaning_resolution_v147 import resolution_fixture


def echo_fixture():
    _, reading, source, selection, findings, response = resolution_fixture()
    response.edits = [MeaningResolutionEdit(meaning_id='part-0:meaning-1', required_meanings=[
        RequiredMeaning(meaning='The system schedules appointments after staff training.')]),
        MeaningResolutionEdit(meaning_id='part-0:meaning-2', required_meanings=[
            RequiredMeaning(meaning=selection.decisions[0].required_meanings[1].meaning)])]
    disposition = response.finding_dispositions[0]
    disposition.action, disposition.classification = 'corrected', 'missing_qualification'
    disposition.referenced_meaning_ids = ['part-0:meaning-1', 'part-0:meaning-2']
    disposition.reason = 'Attach the training condition to the scheduling assertion.'
    return reading, source, selection, findings, response


@pytest.mark.parametrize('quote', ['empty', 'original'])
def test_protected_echo_preserves_original_wording_and_evidence_without_mutating_inputs(quote):
    _, source, selection, findings, response = echo_fixture()
    if quote == 'original':
        response.edits[1].required_meanings[0].source_quote = selection.decisions[0].required_meanings[1].source_quote
    before = deepcopy((source, selection, findings, response))
    canonical = response.model_copy(deep=True)
    canonical.edits.pop()
    actual = apply_meaning_resolution(selection, response, findings, source)
    assert actual == apply_meaning_resolution(selection, canonical, findings, source)
    assert actual.decisions[0].required_meanings[1:] == selection.decisions[0].required_meanings[1:]
    assert actual.decisions[1] == selection.decisions[1]
    assert (source, selection, findings, response) == before


@pytest.mark.parametrize('fault', ['rewrite', 'whitespace_change', 'extra_meaning', 'empty_meanings',
    'foreign_quote', 'unknown_id', 'duplicate_echo', 'duplicate_edit', 'unaffected_part',
    'omitted_part', 'false_corrected', 'unresolved_finding'])
def test_echo_cannot_authorize_changes_or_satisfy_a_correction(fault):
    _, source, selection, findings, response = echo_fixture()
    echo = response.edits[1]
    if fault == 'rewrite': echo.required_meanings[0].meaning += ' Always.'
    elif fault == 'whitespace_change': echo.required_meanings[0].meaning += ' '
    elif fault == 'extra_meaning': echo.required_meanings.append(deepcopy(echo.required_meanings[0]))
    elif fault == 'empty_meanings': echo.required_meanings.clear()
    elif fault == 'foreign_quote': echo.required_meanings[0].source_quote = 'Foreign evidence.'
    elif fault == 'unknown_id': echo.meaning_id = 'part-0:meaning-999'
    elif fault == 'duplicate_echo': response.edits.append(deepcopy(echo))
    elif fault == 'duplicate_edit': response.edits.append(deepcopy(response.edits[0]))
    elif fault in {'unaffected_part', 'omitted_part'}:
        selection.decisions[1].include = fault == 'unaffected_part'
        selection.decisions[1].required_meanings = deepcopy(echo.required_meanings)
        echo.meaning_id = 'part-1:meaning-1'
    elif fault == 'false_corrected': response.edits.pop(0)
    else: response.finding_dispositions.clear()
    before = deepcopy((source, selection, findings, response))
    with pytest.raises(ValueError):
        apply_meaning_resolution(selection, response, findings, source)
    assert (source, selection, findings, response) == before


def test_echo_may_reference_already_covered_assertion_without_becoming_an_edit():
    _, _, source, selection, findings, response = resolution_fixture()
    response.edits = [MeaningResolutionEdit(meaning_id='part-0:meaning-2',
        required_meanings=[RequiredMeaning(meaning=selection.decisions[0].required_meanings[1].meaning)])]
    assert apply_meaning_resolution(selection, response, findings, source) == selection


def test_raw_echo_and_disposition_remain_auditable_and_prompt_names_editable_ids():
    reading, source, selection, findings, response = echo_fixture()
    verdict = IntroductionAudienceReview(accepted=False, reason='Attach the required qualifier.',
        findings=[{k: v for k, v in f.items() if k != 'finding_id'} for f in findings])
    client = ResolutionGateway(response)
    draft, ledger = resolve_meaning_findings(client, source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading)
    record = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert record['response'] == response.model_dump(mode='json')
    assert record['coalesced_unchanged_meaning_ids'] == ledger['coalesced_unchanged_meaning_ids'] == ['part-0:meaning-2']
    assert record['semantic_approval'] is ledger['semantic_approval'] is False
    assert not reading.audience_selection and reading.audience_part_ids is None
    assert record['decisions_after'] == draft.model_dump(mode='json')['decisions']
    assert len(client.messages) == 1
    payload = json.loads(client.messages[0][-1]['content'].split('\n', 1)[1].rsplit('\n', 1)[0])
    assert payload['editable_meaning_ids'] == ['part-0:meaning-1']
    assert 'Do not echo unchanged meanings in edits' in client.messages[0][0]['content']


def test_saved_echo_replay_only_validates_protocol_without_changing_checkpoint(tmp_path):
    from scripts.replay_meaning_resolution import replay
    reading, _, selection, findings, response = echo_fixture()
    reading.plan_audits.append({'introduction_meaning_resolution': dict(
        response=response.model_dump(mode='json'), findings=findings,
        decisions_before=selection.model_dump(mode='json')['decisions'])})
    data = dict(pipeline_version='saved-version', failure_details={'kind': 'verification'},
        validation_warnings=[dict(code='company_introduction_summary_audit', message=reading.model_dump_json())])
    path = tmp_path / 'checkpoint.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    before = path.read_bytes()
    report = replay(path)
    assert path.read_bytes() == before
    assert report['replay_status'] == 'protocol_validated' and report['model_requests'] == 0
    assert report['semantic_approval'] is False
    assert report['coalesced_unchanged_meaning_ids'] == ['part-0:meaning-2']
