"""A shared predicate must be checked against every explicitly written pair."""
import pytest

from adaptive_document_agent.models import Observation, PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator, apply_structured_issue_replacement
from adaptive_document_agent.validation.direction_scope import resolve_direction_scope

DATES = ['2021-12-31', '2022-12-31', '2023-12-31', '2024-06-30']


def observations(values):
    return [Observation(id=f'obs-{i}', metric_original='Balance', raw_value=str(value),
                        value=value, period=date, period_type='balance_sheet_date',
                        period_basis='point_in_time', unit='count', confidence=1)
            for i, (date, value) in enumerate(zip(DATES, values, strict=True))]


def issues(copy, values):
    obs = observations(values)
    slide = PresentationSlide(id='page', slide_type='analysis', title='Balance', message=copy,
                              observation_ids=[o.id for o in obs])
    return ClaimValidator().validate_slide(slide, obs)


@pytest.mark.parametrize('connector', ['and from', ', and from'])
def test_adjacent_ranges_share_a_verb_then_reverse(connector):
    copy = (f'Balance rose from 2021-12-31 to 2022-12-31 {connector} 2022-12-31 to 2023-12-31, '
            'then fell from 2023-12-31 to 2024-06-30.')
    assert not issues(copy, [100, 120, 140, 90])


@pytest.mark.parametrize('values,wrong_pair', [([100, 90, 140, 80], DATES[:2]),
                                              ([100, 140, 120, 80], DATES[1:3])])
def test_net_increase_cannot_hide_a_wrong_segment(values, wrong_pair):
    copy = 'Balance rose from 2021-12-31 to 2022-12-31 and from 2022-12-31 to 2023-12-31.'
    found = issues(copy, values)
    assert len(found) == 1 and found[0].code == 'directional_contradiction'
    assert [found[0].start_period, found[0].end_period] == wrong_pair
    # Replacing the shared verb would corrupt the other, correct comparison.
    assert found[0].repair_blocked_reason
    assert apply_structured_issue_replacement(copy, found[0]) == (copy, False)


def test_unmentioned_gap_is_not_used_to_compare_two_explicit_ranges():
    assert not issues('Balance rose from 2021-12-31 to 2022-12-31 and from 2023-12-31 to 2024-06-30.',
                      [100, 120, 50, 60])


def test_continuous_claim_still_checks_interior_values_inside_each_pair():
    found = issues('Balance steadily rose from 2021-12-31 to 2023-12-31 and from 2023-12-31 to 2024-06-30.',
                   [100, 90, 120, 140])
    assert any(e.code == 'non_monotonic_claim' for e in found)


@pytest.mark.parametrize('second', ['from 2022-12-31 to 2020-12-31',
                                  'from 2023-12-31 to 2022-12-31',
                                  'from 2022-12-31 to 2025-12-31'])
def test_each_pair_requires_known_chronological_endpoints(second):
    found = issues('Balance rose from 2021-12-31 to 2022-12-31 and ' + second + '.', [100, 120, 140, 80])
    assert any(e.code == 'direction_scope_ambiguous' for e in found)


@pytest.mark.parametrize('tail', [
    'because of the comparison from 2022-12-31 to 2023-12-31',
    'rather than from 2022-12-31 to 2023-12-31',
    'and from 2022-12-31 to 2023-12-31, measured at 2024-06-30',
    'and 2022-12-31 to 2023-12-31',
])
def test_nested_or_incompletely_bound_ranges_are_not_assumed_to_share_a_predicate(tail):
    text = 'Balance rose from 2021-12-31 to 2022-12-31 ' + tail
    direction = ('balance', 'rose', text.index('rose'), text.index('rose') + 4)
    result = resolve_direction_scope(text, [direction], direction, observations([100, 120, 140, 80]),
                                     lambda a, b: b.value - a.value)
    assert result.error and result.segments is None


def test_all_written_ranges_remain_separate():
    text = ('Balance rose from 2021-12-31 to 2022-12-31, from 2022-12-31 to 2023-12-31, '
            'and from 2023-12-31 to 2024-06-30')
    direction = ('balance', 'rose', 8, 12)
    result = resolve_direction_scope(text, [direction], direction, observations([100, 120, 140, 160]),
                                     lambda a, b: b.value - a.value)
    assert not result.error
    assert [[o.period for o in scope.observations] for scope in result.individual_scopes()] == [
        DATES[:2], DATES[1:3], DATES[2:]]
