"""An exact mirrored inclusion is transport redundancy, never semantic approval."""
from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.introduction_meaning_resolution import (
    MeaningResolutionAddition, apply_meaning_resolution, finding_inventory, resolve_meaning_findings)
from tests.test_introduction_disposition_evidence_v153 import ResolutionGateway
from tests.test_introduction_mixed_resolution_v149 import mixed_fixture


def mirrored_fixture():
    reading, source, selection, verdict, response = mixed_fixture()
    inclusion = response.inclusions[0]
    response.additions.append(MeaningResolutionAddition(
        part_id=inclusion.part_id, required_meanings=deepcopy(inclusion.required_meanings)))
    return reading, source, selection, verdict, response


def test_exact_mirror_preserves_explicit_inclusion_once_without_mutating_inputs():
    _, source, selection, verdict, response = mirrored_fixture()
    before = deepcopy((source, selection, verdict, response))
    canonical = response.model_copy(deep=True)
    canonical.additions.pop()
    expected = apply_meaning_resolution(selection, canonical, finding_inventory(verdict), source)
    actual = apply_meaning_resolution(selection, response, finding_inventory(verdict), source)
    assert actual == expected
    assert (source, selection, verdict, response) == before
    included = next(d for d in actual.decisions if d.part_id == response.inclusions[0].part_id)
    assert included.include and included.reason == response.inclusions[0].reason
    assert included.required_meanings == response.inclusions[0].required_meanings


@pytest.mark.parametrize('fault', ['different_claim', 'different_quote', 'extra_claim',
    'missing_inclusion', 'duplicate_inclusion', 'duplicate_addition', 'blank_reason',
    'false_include', 'unknown_part', 'unidentified_part', 'not_corrected', 'missing_finding'])
def test_overlap_never_authorizes_ambiguous_or_unowned_changes(fault):
    _, source, selection, verdict, response = mirrored_fixture()
    addition, inclusion = response.additions[-1], response.inclusions[0]
    if fault == 'different_claim': addition.required_meanings[0].meaning += ' Always.'
    elif fault == 'different_quote': addition.required_meanings[0].source_quote = 'Different evidence.'
    elif fault == 'extra_claim': addition.required_meanings.append(deepcopy(response.edits[0].required_meanings[0]))
    elif fault == 'missing_inclusion': response.inclusions.clear()
    elif fault == 'duplicate_inclusion': response.inclusions.append(deepcopy(inclusion))
    elif fault == 'duplicate_addition': response.additions.append(deepcopy(addition))
    elif fault == 'blank_reason': inclusion.reason = ' '
    elif fault == 'false_include': inclusion.include = False
    elif fault == 'unknown_part': addition.part_id = inclusion.part_id = 'unknown'
    elif fault == 'unidentified_part': addition.part_id = inclusion.part_id = 'part-3'
    elif fault == 'not_corrected': response.finding_dispositions[-1].action = 'outside_selected_scope'
    else: response.finding_dispositions.pop()
    before = deepcopy((source, selection, response))
    with pytest.raises(ValueError):
        apply_meaning_resolution(selection, response, finding_inventory(verdict), source)
    assert (source, selection, response) == before


def test_resolution_audit_retains_raw_overlap_and_requires_independent_review():
    reading, source, selection, verdict, response = mirrored_fixture()
    client = ResolutionGateway(response)
    draft, ledger = resolve_meaning_findings(client, source, selection,
        selection.model_dump(mode='json')['decisions'], verdict, reading)
    record = reading.plan_audits[-1]['introduction_meaning_resolution']
    assert record['response'] == response.model_dump(mode='json')
    assert record['coalesced_inclusion_addition_part_ids'] == ['part-1']
    assert record['status'] == 'protocol_validated'
    assert record['semantic_approval'] is ledger['semantic_approval'] is False
    assert not reading.audience_selection and reading.audience_part_ids is None
    assert ledger['inclusions'] == response.model_dump(mode='json')['inclusions']
    assert record['decisions_after'] == draft.model_dump(mode='json')['decisions']
    assert len(client.messages) == 1
    assert 'Never repeat an inclusion in additions' in client.messages[0][0]['content']


def test_saved_response_replay_does_not_write_or_certify_a_completed_pipeline(tmp_path):
    from scripts.replay_meaning_resolution import replay
    reading, _, selection, verdict, response = mirrored_fixture()
    reading.plan_audits.append({'introduction_meaning_resolution': dict(
        response=response.model_dump(mode='json'), findings=finding_inventory(verdict),
        decisions_before=selection.model_dump(mode='json')['decisions'])})
    data = dict(pipeline_version='saved-failed-version', failure_details={'kind': 'verification'},
        validation_warnings=[dict(code='company_introduction_summary_audit', message=reading.model_dump_json())])
    path = tmp_path / 'checkpoint.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    before = path.read_bytes()
    report = replay(path)
    assert path.read_bytes() == before
    assert report['replay_status'] == 'protocol_validated' and report['model_requests'] == 0
    assert report['semantic_approval'] is False
    assert report['coalesced_inclusion_addition_part_ids'] == ['part-1']
