"""Native count deltas require exact inputs, intervals, units and Python results."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models import Observation,PresentationSlide
from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support
from adaptive_document_agent.services.presentation_evidence import calculation_catalog
from adaptive_document_agent.validation.calculated_count_change import checked_count_changes
from adaptive_document_agent.validation.claim_validator import ClaimValidator


def rows(values=(-10,-15,-22)):
    return [Observation(id=f'count-{i}',metric_original='Number of exiting distributors',
        period=f'FY{2023+i}',period_type='fiscal_year',raw_value=f'({abs(value)})',
        value=value,unit='count',raw_unit='distributors',unit_family='count',unit_scale=1,
        confidence=1,validation_status='valid',evidence=[dict(page=1,
            text='Synthetic distributor table.',extraction_method='table',confidence=1)])
        for i,value in enumerate(values)]


@pytest.mark.parametrize('text',[
    'Number of exiting distributors had a calculated signed change of -12 distributors from FY2023 to FY2025.',
    'Number of exiting distributors had a calculated change from FY2023 to FY2025 of -12 distributors.',
    'Number of exiting distributors were (10), (15), (22). The calculated signed change was -12 distributors from FY2023 to FY2025.',
])
def test_native_count_delta_has_one_exact_calculation_and_does_not_modify_raw_rows(text):
    obs=rows();before=deepcopy(obs);catalog=calculation_catalog(obs)
    checked=list(checked_count_changes(text,obs,catalog.values()))
    assert len(checked)==1 and checked[0][1] and len(checked[0][2])==1
    assert _numeric_support(text,obs)
    assert obs==before


def test_equivalent_two_row_total_and_annual_deltas_use_one_exact_calculation():
    obs=rows((-10,-22))
    text='Number of exiting distributors had a calculated change of -12 distributors from FY2023 to FY2024.'
    checked=list(checked_count_changes(text,obs,calculation_catalog(obs).values()))
    assert len(checked)==1 and checked[0][1] and len(checked[0][2])==1


@pytest.mark.parametrize('change',[
    '-13 distributors from FY2023 to FY2025',
    '12 distributors from FY2023 to FY2025',
    '-12 dollars from FY2023 to FY2025',
    '-12 distributors from FY2023 to FY2024',
    '-12 distributors from FY2025 to FY2023',
])
def test_wrong_count_result_unit_sign_and_period_are_rejected(change):
    assert not _numeric_support('Number of exiting distributors had a calculated change of '+change+'.',rows())


def test_metric_and_immediate_antecedent_are_required():
    for prefix in ['Other customers had a ',
        'Number of exiting distributors were reported. Other customers were reported. The ']:
        assert not _numeric_support(prefix+'calculated change of -12 distributors from FY2023 to FY2025.',rows())


@pytest.mark.parametrize('message,valid',[
    ('Number of exiting distributors magnitude increased from FY2023 to FY2025.',True),
    ('Number of exiting distributors had an increase in magnitude from FY2023 to FY2025.',True),
    ('Number of exiting distributors magnitude decreased from FY2023 to FY2025.',False),
    ('Number of exiting distributors increased from FY2023 to FY2025.',False),
    ('Number of exiting distributors magnitude increased from FY2023 to FY2029.',False),
])
def test_only_explicit_magnitude_uses_absolute_values(message,valid):
    obs=rows();before=deepcopy(obs)
    slide=PresentationSlide(id='count',slide_type='analysis',title='Distributor counts',
        message=message,observation_ids=[o.id for o in obs])
    issues=ClaimValidator().validate_slide(slide,obs)
    assert (not issues)==valid,issues
    assert obs==before


def test_magnitude_comparison_does_not_hide_non_monotonic_values():
    obs=rows((-10,-25,-22))
    slide=PresentationSlide(id='count',slide_type='analysis',title='Distributor counts',
        message='Number of exiting distributors magnitude increased continuously from FY2023 to FY2025.',
        observation_ids=[o.id for o in obs])
    assert any(i.code=='non_monotonic_claim' for i in ClaimValidator().validate_slide(slide,obs))
