"""Directional predicates belong to ratios, never their mentioned components."""

from __future__ import annotations

import pytest

from adaptive_document_agent.models import Observation, PresentationPlan, PresentationSlide, SourceEvidence
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan


def _series(label: str, values: tuple[float, float], *, percent: bool = False) -> list[Observation]:
    key = label.casefold().replace(' ', '_')
    return [Observation(
        id=f'{key}_{year}', metric_original=label, metric_canonical=key,
        value=value, raw_value=str(value), unit='percent' if percent else 'currency',
        raw_unit='%' if percent else 'USD million', currency=None if percent else 'USD',
        period=f'FY{year}', period_type='fiscal_year', confidence=.95,
        evidence=[SourceEvidence(page=3, text=f'{label}: {value}',
                                 extraction_method='digital_table', confidence=.95)],
    ) for year, value in zip((2022, 2023), values, strict=True)]


def _facts() -> list[Observation]:
    return [*_series('Support and maintenance expense', (40, 50)),
            *_series('Total operating expenditure', (100, 200)),
            *_series('Support and maintenance expense ratio', (40, 25), percent=True)]


def _plan(text: str, observations: list[Observation], component: str = 'message') -> PresentationPlan:
    kwargs = {'title': 'Reported movements', component: [text] if component == 'bullets' else text}
    return PresentationPlan(title='Review', slides=[PresentationSlide(
        id='movement', slide_type='analysis', observation_ids=[o.id for o in observations], **kwargs,
    )])


@pytest.mark.parametrize('component', ['title', 'message', 'bullets'])
@pytest.mark.parametrize('qualifier', [
    'as a percentage of', 'as % of', 'as a share of', 'relative to', 'to',
])
@pytest.mark.parametrize('reverse', [False, True])
def test_ratio_subject_does_not_lend_its_direction_to_denominator(component, qualifier, reverse):
    observations = _facts()
    if reverse:
        observations.reverse()
    text = f'Support and maintenance expense ratio {qualifier} total operating expenditure fell.'
    plan = _plan(text, observations, component)
    raw = [o.model_dump() for o in observations]
    original_plan = plan.model_dump()
    assert not ClaimValidator().validate_plan(plan, observations)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert not repairs
    assert repaired.model_dump() == original_plan
    assert [o.model_dump() for o in observations] == raw


@pytest.mark.parametrize('qualifier', ['as a percentage of', 'as % of', 'as a share of', 'relative to'])
def test_incorrect_ratio_direction_is_repaired_using_ratio_values(qualifier):
    observations = _facts()
    text = f'Support and maintenance expense ratio {qualifier} total operating expenditure rose.'
    plan = _plan(text, observations)
    issues = ClaimValidator().validate_plan(plan, observations)
    assert len(issues) == 1
    assert issues[0].metric_name == 'support_and_maintenance_expense_ratio'
    assert issues[0].expected_direction == 'DECREASED'
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert len(repairs) == 1
    assert repaired.slides[0].message == text.replace('rose', 'fell')
    assert not ClaimValidator().validate_plan(repaired, observations)
    assert not repair_presentation_plan(repaired, observations)[1]


@pytest.mark.parametrize('denominator_verb,expected', [('rose', 'rose'), ('fell', 'rose')])
def test_independent_denominator_predicate_keeps_its_own_expense_direction(denominator_verb, expected):
    observations = _facts()
    prefix = ('Support and maintenance expense ratio as a percentage of '
              'total operating expenditure fell')
    text = f'{prefix} and total operating expenditure {denominator_verb}.'
    plan = _plan(text, observations)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == f'{prefix} and total operating expenditure {expected}.'
    assert len(repairs) == (denominator_verb != expected)
    assert not ClaimValidator().validate_plan(repaired, observations)


def test_component_values_cannot_repair_unbound_ratio_subject():
    observations = _facts()[:4]
    text = ('Support and maintenance expense as a percentage of '
            'total operating expenditure fell.')
    plan = _plan(text, observations)
    issues = ClaimValidator().validate_plan(plan, observations)
    assert any(issue.code == 'direction_scope_ambiguous' for issue in issues)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


@pytest.mark.parametrize('text', [
    'Total operating expenditure fell.',
    'Support and maintenance expense fell.',
])
def test_legitimate_expense_claims_still_repair(text):
    observations = _facts()
    plan = _plan(text, observations)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert len(repairs) == 1
    assert repaired.slides[0].message == text.replace('fell', 'rose')
    assert not ClaimValidator().validate_plan(repaired, observations)


def test_source_derived_short_ratio_initialism_keeps_its_own_direction():
    observations = [*_series('Annual support and maintenance expenditure', (40, 50)),
                    *_series('Annual total operating expenditure', (100, 200)),
                    *_series('Annual support and maintenance expenditure ratio %', (40, 25), percent=True)]
    text = ('S&M Expenditure Rose while S&M Ratio to Total Operating Expenditure Fell')
    plan = _plan(text, observations, 'title')
    assert not ClaimValidator().validate_plan(plan, observations)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].title == text
    assert not repairs
    plan.slides[0].title = text.replace(' Fell', ' Rose')
    issues = ClaimValidator().validate_plan(plan, observations)
    assert len(issues) == 1
    assert 'ratio' in issues[0].metric_name
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].title == text
    assert len(repairs) == 1


@pytest.mark.parametrize('connector', [' / ', ' as % of '])
def test_explicit_quotient_does_not_borrow_a_component_direction(connector):
    observations = _facts()[:4]
    text = f'Support and maintenance expense{connector}total operating expenditure fell.'
    plan = _plan(text, observations)
    assert any(issue.code == 'direction_scope_ambiguous'
               for issue in ClaimValidator().validate_plan(plan, observations))
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


@pytest.mark.parametrize('label', [
    'Accepted responses / Invited responses',
    'Accepted responses as a percentage of Invited responses',
    'Ratio of Accepted responses to Invited responses',
])
def test_exact_compound_ratio_label_outranks_nested_component_labels(label):
    observations = [*_series('Accepted responses', (40, 50)),
                    *_series('Invited responses', (100, 200)),
                    *_series(label, (40, 25), percent=True)]
    text = f'{label} fell.'
    plan = _plan(text, observations)
    assert not ClaimValidator().validate_plan(plan, observations)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


@pytest.mark.parametrize('denominator', ['Total operating expenditure', 'Staffing expenditure'])
def test_short_ratio_alias_collision_cannot_borrow_denominator_words(denominator):
    observations = [*_series('Support and maintenance equipment expenditure ratio', (40, 25), percent=True),
                    *_series('Support and maintenance staffing expenditure ratio', (20, 30), percent=True),
                    *_series(denominator, (100, 200))]
    text = f'S&M ratio to {denominator} fell.'
    plan = _plan(text, observations)
    issues = ClaimValidator().validate_plan(plan, observations)
    assert any(issue.code == 'direction_scope_ambiguous' for issue in issues)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


def test_unknown_ratio_cannot_borrow_only_selected_metric_or_matching_values():
    observations = _series('Total operating expenditure', (100, 200))
    text = 'Unknown completion ratio to total operating expenditure fell from 100 to 200.'
    plan = _plan(text, observations)
    assert any(issue.code == 'direction_scope_ambiguous'
               for issue in ClaimValidator().validate_plan(plan, observations))
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


@pytest.mark.parametrize('label', ['Completion rate', 'Operating margin', 'Acceptance share'])
def test_other_ratio_measure_labels_keep_denominator_as_a_qualifier(label):
    observations = [*_series(label, (40, 25), percent=True),
                    *_series('Eligible responses', (100, 200))]
    text = f'{label} as a percentage of eligible responses fell.'
    plan = _plan(text, observations)
    assert not ClaimValidator().validate_plan(plan, observations)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


def test_independent_ratios_with_opposite_trends_keep_their_own_predicates():
    observations = [*_facts(), *_series('Completion ratio', (20, 30), percent=True),
                    *_series('Invited responses', (200, 100))]
    correct = ('Support and maintenance expense ratio to total operating expenditure fell '
               'and completion ratio to invited responses rose.')
    plan = _plan(correct, observations)
    assert not ClaimValidator().validate_plan(plan, observations)
    plan.slides[0].message = correct.replace('responses rose', 'responses fell')
    raw = [item.model_dump() for item in observations]
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == correct
    assert len(repairs) == 1
    assert not ClaimValidator().validate_plan(repaired, observations)
    assert [item.model_dump() for item in observations] == raw


@pytest.mark.parametrize('unit', ['percentage points', 'percentage point', 'percentage-point'])
def test_percentage_point_delta_unit_is_not_another_ratio_subject(unit):
    observations = _series('Service margin', (30, 25), percent=True)
    text = f'Service margin declined by 5 {unit} from FY2022 to FY2023.'
    plan = _plan(text, observations)
    assert not ClaimValidator().validate_plan(plan, observations)
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs
    plan.slides[0].message = text.replace('declined', 'increased')
    issues = ClaimValidator().validate_plan(plan, observations)
    assert len(issues) == 1
    assert issues[0].metric_name == 'service_margin'
    assert issues[0].expected_direction == 'DECREASED'
    assert issues[0].code == 'directional_contradiction'
