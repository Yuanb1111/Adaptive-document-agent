"""Audit rationale capacity is consistent across writer, repair and canonical selection."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.introduction_audience import (
    AUDIENCE_REASON_MAX_LENGTH, AudienceDecision, IntroductionAudienceSelection)
from adaptive_document_agent.agent.introduction_meaning_resolution import (
    IntroductionMeaningResolution, MeaningResolutionInclusion, apply_meaning_resolution, finding_inventory)
from tests.test_introduction_mixed_resolution_v149 import mixed_fixture


@pytest.mark.parametrize('length', [241, 317, 2000])
def test_complete_bounded_audit_reason_survives_wire_apply_and_canonical_validation(length):
    _, source, selection, verdict, original = mixed_fixture()
    reason = ('A source-aware explanation of audience relevance and necessary conditions. ' * 40)[:length]
    wire = original.model_dump(mode='json')
    wire['inclusions'][0]['reason'] = reason
    response = IntroductionMeaningResolution.model_validate_json(
        IntroductionMeaningResolution.model_validate(wire).model_dump_json())
    updated = apply_meaning_resolution(selection, response, finding_inventory(verdict), source)
    canonical = IntroductionAudienceSelection.model_validate_json(updated.model_dump_json())
    assert canonical.decisions[1].reason == response.inclusions[0].reason == reason
    assert canonical.decisions[0] == updated.decisions[0]
    assert canonical.decisions[2:] == selection.decisions[2:]
    assert len(canonical.decisions[1].reason) == length


@pytest.mark.parametrize('schema', [AudienceDecision, MeaningResolutionInclusion])
@pytest.mark.parametrize('fault', ['missing', 'empty', 'over_limit'])
def test_reason_remains_required_and_bounded_in_both_wire_and_canonical_schema(schema, fault):
    value = dict(part_id='owned-part', include=True, reason='Evidence-based importance.',
                 required_meanings=[dict(meaning='The source states an availability condition.')])
    if fault == 'missing': value.pop('reason')
    elif fault == 'empty': value['reason'] = ''
    else: value['reason'] = 'x' * (AUDIENCE_REASON_MAX_LENGTH + 1)
    with pytest.raises(ValueError):
        schema.model_validate(value)


def test_nonblank_reason_protocol_is_unchanged_and_capacity_does_not_accept_semantic_copy():
    _, source, selection, verdict, response = mixed_fixture()
    before = deepcopy(selection)
    response.inclusions[0].reason = ' ' * 317
    with pytest.raises(ValueError, match='explicit reason'):
        apply_meaning_resolution(selection, response, finding_inventory(verdict), source)
    assert selection == before
    assert AudienceDecision.model_json_schema()['properties']['reason']['maxLength'] == 2000
    assert MeaningResolutionInclusion.model_json_schema()['properties']['reason']['maxLength'] == 2000
