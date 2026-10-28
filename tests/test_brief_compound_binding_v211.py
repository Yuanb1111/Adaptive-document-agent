"""Compound reviewer bindings can use one correction; uncertainty still fails."""
import json

import pytest

from adaptive_document_agent.agent.brief_meaning_review import meaning_validator
from tests.test_brief_direction_repair_v174 import loss_fixture, ScriptedGateway


def compound_fixture():
    brief, result, original, initial, corrected, final = loss_fixture()
    # One reviewer endpoint pair incorrectly owns a heading with two measures.
    original['items'][0]['comparisons'][0]['claim'] = brief.items[0].label
    row = initial['items'][0]['comparisons'][0]
    row.update(claim=brief.items[0].label, predicate='widen as revenue grows',
               direction='uncertain', reason='This compound heading needs one binding per measure.')
    initial['items'][0]['omitted_directional_claims'] = []
    return brief, result, original, initial, corrected, final


def test_compound_and_unasserted_bindings_are_corrected_without_rewriting_audience_copy():
    brief, result, original, initial, corrected, final = compound_fixture()
    before = brief.model_dump_json(), result.document.model_dump_json()
    gateway = ScriptedGateway([original, initial, corrected, final])
    validate = meaning_validator(gateway, result=result)
    assert validate(brief) == {} and validate(brief) == {}
    assert len(gateway.calls) == 4
    assert before == (brief.model_dump_json(), result.document.model_dump_json())
    audit = json.loads(next(w.message for w in reversed(result.validation_warnings)
                           if w.code == 'executive_brief_comparison_correction_audit'))
    assert audit['status'] == 'accepted'
    assert 'comparison_index=0' in str(audit['direction_errors'])
    assert 'Source comparison infers a direction' in str(audit['direction_errors'])


def test_unchanged_ambiguous_binding_fails_after_one_correction_without_looping():
    brief, result, original, initial, _, _ = compound_fixture()
    gateway = ScriptedGateway([original, initial, original, initial])
    validate = meaning_validator(gateway, result=result)
    errors = validate(brief)
    assert 'Audience direction is ambiguous' in str(errors)
    assert validate(brief) == errors and len(gateway.calls) == 4
    audit = json.loads(next(w.message for w in reversed(result.validation_warnings)
                           if w.code == 'executive_brief_comparison_correction_audit'))
    assert audit['status'] == 'rejected'


@pytest.mark.parametrize('failure', ['wrong_direction', 'wrong_source', 'source_rejection'])
def test_splitting_never_bypasses_arithmetic_or_source_rejection(failure):
    brief, result, original, initial, corrected, _ = compound_fixture()
    if failure == 'wrong_direction':
        corrected['items'][0]['comparisons'][0]['direction'] = 'decrease'
    elif failure == 'wrong_source':
        corrected['items'][0]['comparisons'][0]['start_ref'] = 'not_owned'
    else:
        corrected['items'][0].update(accepted=False, reason='Source qualifications are missing.')
    gateway = ScriptedGateway([original, initial, corrected])
    assert meaning_validator(gateway, result=result)(brief)
    assert len(gateway.calls) == 3
