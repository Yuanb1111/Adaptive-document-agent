"""Period coverage must not create empty or broadened pre-existing bullet scopes."""
from copy import deepcopy

import pytest

from adaptive_document_agent.services.presentation_period_scope import prepare_presentation_period_scope
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_presentation_period_scope import _sample


def _validate_with_required_pages(result):
    from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
    full = PresentationPlanRecovery().fallback(result, validate=False)
    full.slides = [*full.slides[:3], *result.presentation_plan.slides,
                   *(slide for slide in full.slides[3:] if slide.slide_type != 'analysis')]
    PresentationPlanValidator().validate(full, result)


@pytest.mark.parametrize('count', [1, 5])
def test_unscoped_bullets_keep_their_prior_chart_evidence_when_separate_periods_are_added(count):
    result = _sample()
    slide = result.presentation_plan.slides[0]
    slide.bullets = ['Defects and repairs increased over the track record period.'] * count
    original = deepcopy(result.observations), deepcopy(result.charts)
    old_ids = {oid for chart in result.charts for oid in chart.observation_ids}
    extra_ids = {o.id for o in result.observations if o.period_basis == '6M'}
    assert not slide.observation_ids and not slide.bullet_observation_ids
    prepare_presentation_period_scope(result)
    if count == 1:
        assert set(slide.bullet_observation_ids[0]) == old_ids
        assert set(slide.bullet_observation_ids[1]) == extra_ids
    else:
        assert all(set(scope) == old_ids for scope in slide.bullet_observation_ids[:-1])
        assert set(slide.bullet_observation_ids[-1]) == old_ids | extra_ids
    assert set(slide.observation_ids) == old_ids | extra_ids
    assert all(scope for scope in slide.bullet_observation_ids)
    _validate_with_required_pages(result)
    assert (result.observations, result.charts) == original
    after = result.model_dump()
    assert prepare_presentation_period_scope(result) == [] and result.model_dump() == after


def test_explicit_per_bullet_evidence_is_not_broadened_to_companion_periods():
    result = _sample()
    slide = result.presentation_plan.slides[0]
    scopes = [list(chart.observation_ids) for chart in result.charts]
    slide.bullets = ['Defects increased over the track record period.', 'Repairs increased over the track record period.']
    slide.bullet_observation_ids = deepcopy(scopes)
    slide.observation_ids = [oid for scope in scopes for oid in scope]
    prepare_presentation_period_scope(result)
    assert slide.bullet_observation_ids[:2] == scopes
    assert all('6M' in oid for oid in slide.bullet_observation_ids[2])
    _validate_with_required_pages(result)


def test_malformed_existing_scope_is_not_replaced_by_a_guessed_binding():
    result = _sample()
    slide = result.presentation_plan.slides[0]
    slide.bullets = ['Defects increased over the track record period.']
    slide.bullet_observation_ids = [[]]
    before = slide.model_dump()
    assert prepare_presentation_period_scope(result) == []
    assert slide.model_dump() == before
    assert result.validation_warnings[-1].code == 'presentation_period_scope_unresolved'
