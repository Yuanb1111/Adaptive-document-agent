import pytest

from adaptive_document_agent.models import Observation, PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.direction_scope import inherited_period_range


def observations():
    return [Observation(id=f'obs-{i}', metric_original='Balance', raw_value=str(value),
                        value=value, period=period, period_type='balance_sheet_date',
                        period_basis='point_in_time', unit='count', confidence=1)
            for i, (period, value) in enumerate([
                ('2021-12-31', 100), ('2022-12-31', 120), ('2024-10-31', 80)])]


@pytest.mark.parametrize('direction,valid', [('increase', True), ('decrease', False)])
def test_date_reference_checks_previous_pair_instead_of_whole_series(direction, valid):
    obs = observations()
    copy = ('Balance was 100 at 2021-12-31 and 120 at 2022-12-31. '
            f'The source attributes the {direction} between those dates to demand. '
            'Balance was 80 at 2024-10-31.')
    slide = PresentationSlide(id='page', slide_type='analysis', title='Balance',
                              message=copy, observation_ids=[o.id for o in obs])
    errors = ClaimValidator().validate_slide(slide, obs)
    assert bool(errors) is not valid
    if not valid:
        assert any(e.code == 'directional_contradiction' for e in errors)


@pytest.mark.parametrize('previous', [
    '', 'Balance was 100 at 2021-12-31.', 'Balance was 100 in 2021 and 120 in 2022.',
    'Balance was 100 at 2021-12-31, 120 at 2022-12-31 and 80 at 2024-10-31.',
    'Balance was 100 at 2021-12-31 and 120 at 2022-12-31. Demand was strong.',
])
def test_unclear_date_reference_cannot_use_data_endpoints_or_an_older_sentence(previous):
    claim = 'Balance increased between those dates.'
    copy = previous + ' ' + claim
    period, error = inherited_period_range(copy, copy.index('increased'), claim)
    assert error and not period


@pytest.mark.parametrize('copy,valid', [
    ('Balance was 100 at 2021-12-31 and rose to 120 at 2022-12-31.', True),
    ('Balance was 100 at 2021-12-31 and fell to 120 at 2022-12-31.', False),
    ('Balance was 120 at 2022-12-31 and fell to 80 at 2024-10-31.', True),
    ('Balance was 100 and rose to 120 at 2022-12-31.', False),
    ('Balance was 100 at 2020-12-31 and rose to 120 at 2022-12-31.', False),
    ('Balance was 120 at 2022-12-31 and fell to 100 at 2021-12-31.', False),
    ('Balance rose from 100 on 2021-12-31 to 120 on 2022-12-31.', True),
    ('Balance fell from 100 on 2021-12-31 to 120 on 2022-12-31.', False),
])
def test_dated_baseline_and_direction_share_only_the_written_endpoints(copy, valid):
    obs = observations()
    slide = PresentationSlide(id='page', slide_type='analysis', title='Balance',
                              message=copy, observation_ids=[o.id for o in obs])
    errors = ClaimValidator().validate_slide(slide, obs)
    assert bool(errors) is not valid
