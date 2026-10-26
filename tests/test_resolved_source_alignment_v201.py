import pytest

from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan
from tests.test_repeated_source_direction import _case


def case():
    observations, plan, chart = _case(metric='Completed jobs')
    for index, observation in enumerate(observations):
        observation.metric_original = 'Finished jobs' if index < 3 else 'Jobs completed'
        observation.metric_canonical = 'Completed jobs'
        observation.unit = observation.unit_family = 'count'
        observation.value = abs(observation.value)
    plan.slides[0].message = 'Completed jobs declined from FY2022 to FY2024.'
    return observations, plan, chart


def test_existing_semantic_mapping_can_align_complete_duplicate_disclosures():
    observations, plan, chart = case()
    original = [o.model_dump() for o in observations]
    assert ClaimValidator().validate_plan(plan, observations, [chart])
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])
    assert repairs and repaired.slides[0].observation_ids == [o.id for o in observations[:3]]
    assert not ClaimValidator().validate_plan(repaired, observations, [chart])
    assert [o.model_dump() for o in observations] == original


@pytest.mark.parametrize('field,value', [('value', 44), ('audited_status', 'unaudited'),
    ('currency', 'USD'), ('unit_scale', 1), ('period_end', '2024-11-30'), ('ifrs_status', 'ADJUSTED')])
def test_semantic_alias_cannot_override_value_or_scope_conflict(field, value):
    observations, plan, chart = case()
    setattr(observations[-1], field, value)
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])
    assert not repairs
    assert ClaimValidator().validate_plan(repaired, observations, [chart])


def test_without_retained_semantic_mapping_python_does_not_guess_synonyms():
    observations, plan, chart = case()
    for observation in observations:
        observation.metric_canonical = None
    repaired, repairs = repair_presentation_plan(plan, observations, [chart])
    assert not repairs and repaired.slides[0].observation_ids == plan.slides[0].observation_ids


def test_broad_canonical_mapping_does_not_erase_source_ratio_qualifier():
    observations, plan, chart = case()
    for observation in observations[3:]:
        observation.metric_original = 'Completed jobs: % of Total'
    _, repairs = repair_presentation_plan(plan, observations, [chart])
    assert not repairs


def test_distinct_source_choices_preserve_conflicting_audit_status_and_complete_periods():
    from adaptive_document_agent.services.presentation_source_series import distinct_source_series
    observations, _, _ = case()
    assert distinct_source_series(observations) == [observations]
    observations[-1].audited_status = 'unaudited'
    groups = distinct_source_series(observations)
    assert groups == [observations[:3], observations[3:]]
    assert all(len({o.period for o in g}) == 3 for g in groups)
    assert groups[1][-1].audited_status == 'unaudited'


def test_source_directory_keeps_each_conflicting_disclosure_selectable():
    from adaptive_document_agent.agent.presentation_topic_selector import series_directory
    from tests.test_pptx_export import _result
    result = _result()
    obs, _, _ = case()
    obs[-1].audited_status = 'unaudited'
    result.observations = obs
    _, lookup = series_directory(result)
    assert {frozenset(o.id for o in g) for g in lookup.values()} == {
        frozenset(o.id for o in obs[:3]), frozenset(o.id for o in obs[3:])}
