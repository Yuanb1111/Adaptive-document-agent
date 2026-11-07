import pytest

from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support
from adaptive_document_agent.services.calendar_claims import bound_period_dates
from adaptive_document_agent.validation.presentation_numeric_evidence import checked_money_amounts
from tests.test_topic_coverage_review import _observation


@pytest.mark.parametrize('last, accepted', [
    ('October 31, 2024', True), ('31 Oct 2024', True),
    ('December 31, 2024', False), ('February 31, 2024', False),
    ('2021-10-31', False)])
def test_retained_finding_requires_whole_source_dates(last, accepted):
    dates = ['2021-12-31', '2024-10-31']
    observations = [_observation('Population', period, value) for period, value in zip(dates, [100, 120])]
    copy = f'Population rose from December 31, 2021 to {last}.'
    assert _numeric_support(copy, observations) is accepted
    if accepted:
        assert bound_period_dates(copy, dates) == 'Population rose from 2021-12-31 to 2024-10-31.'
        assert not _numeric_support(copy + ' The final value was 999.', observations)


def test_hyphenated_iso_comparison_still_requires_both_complete_source_dates():
    periods = ['2021-12-31', '2024-06-30']
    obs = [_observation('Population', p, v) for p, v in zip(periods, [100, 120])]
    copy = 'The source attributes the 2021-12-31-to-2024-06-30 increase to demand.'
    assert bound_period_dates(copy, periods) == copy.replace('-to-', ' to ')
    assert _numeric_support(copy, obs)
    assert not _numeric_support(copy.replace('2024-06-30', '2024-10-31'), obs)
    assert bound_period_dates('id-2021-12-31-to-2024-06-30', periods) == 'id-2021-12-31-to-2024-06-30'


def test_binding_feedback_identifies_missing_value_and_does_not_infer_fiscal_year_end():
    obs = [_observation('Population', 'FY2023', 100)]
    failures = []
    assert not _numeric_support('Population was 999 in FY2023.', obs, diagnostics=failures)
    assert '999' in failures[0]
    failures.clear()
    assert not _numeric_support('Population was 100 at 2023-12-31.', obs, diagnostics=failures)
    assert 'FY2023' in failures[0] and 'calendar date' in failures[0]


@pytest.mark.parametrize('copy, supported', [
    ('Net assets (RMB in thousands) were RMB 345,007 at 2021-12-31.', [True]),
    ('RMB in thousands. Net assets were CNY 345,007.', [True]),
    ('Figures follow.\nRMB in thousands: net assets were RMB 345,007.', [True]),
    ('Net assets (RMB in thousands) were RMB 345,008.', [False]),
    ('Net assets (RMB in thousands) were HKD 345,007.', [False]),
    ('Net assets (RMB in thousands) were RMB 345,007 million.', [False]),
    ('Net assets (RMB in thousands) were RMB 345.007 million.', [True]),
    ('Net assets (RMB in thousands) were RMB 345,007.\nElsewhere: RMB 345,007.', [True, False]),
    ('RMB in thousands. Net assets (RMB in units) were RMB 345,007.', [False]),
    ('Net assets were RMB 345,007 (RMB in thousands).', [False]),
])
def test_declared_money_scale_is_scoped_and_still_requires_a_bound_amount(copy, supported):
    observation = _observation('Net assets', '2021-12-31', 345_007_000).model_copy(update={
        'raw_value': '345,007', 'raw_unit': 'RMB in thousands', 'unit': 'currency', 'currency': 'CNY',
    })
    assert [bound for _, bound, _ in checked_money_amounts(copy, [observation])] == supported
    assert _numeric_support(copy, [observation]) is all(supported)


@pytest.mark.parametrize('amount,supported', [
    ('(RMB33,068) thousand', True), ('(RMB33,068 thousand)', True),
    ('(RMB33.068 million)', True), ('(CNY33,068) thousand', True),
    ('RMB33,068 thousand', False), ('(RMB+33,068) thousand', False),
    ('positive (RMB33,068) thousand', False), ('(USD33,068) thousand', False),
    ('(RMB33,068) million', False), ('(RMB33,069) thousand', False),
    ('(RMB33,068 million) thousand', False),
])
def test_accounting_amount_keeps_currency_scale_and_typed_negative_sign(amount, supported):
    observation = _observation('Reserves', '2024-06-30', -33_068_000).model_copy(update={
        'raw_value': '(33,068)', 'raw_unit': 'RMB in thousands', 'unit': 'currency', 'currency': 'CNY',
    })
    copy = f'Reserves were {amount} at 2024-06-30.'
    assert [ok for _, ok, _ in checked_money_amounts(copy, [observation])] == [supported]
    assert _numeric_support(copy, [observation]) is supported
    positive = observation.model_copy(update={'value': 33_068_000})
    assert not all(ok for _, ok, _ in checked_money_amounts(
        'Reserves were (RMB33,068) thousand.', [positive]))


@pytest.mark.parametrize('period', ['30 Jun 2024', 'June 30, 2024', '2024-06-30'])
@pytest.mark.parametrize('written', ['30 Jun 2024', 'June 30, 2024', '2024-06-30'])
def test_spelled_source_period_and_iso_claim_have_the_same_complete_date(period, written):
    rows = [_observation('Population', period, 188_474)]
    original = rows[0].model_dump()
    assert bound_period_dates(f'At {written}, population was 188,474.', [period]) == (
        'At 2024-06-30, population was 188,474.')
    assert _numeric_support(f'At {written}, population was 188,474.', rows)
    assert not _numeric_support('At 31 Jul 2024, population was 188,474.', rows)
    assert not _numeric_support('At 30 Jun 2025, population was 188,474.', rows)
    assert rows[0].model_dump() == original


@pytest.mark.parametrize('period', ['FY2024', '6M2024', '31 Feb 2024'])
def test_non_calendar_or_invalid_period_cannot_license_a_calendar_date(period):
    assert bound_period_dates('At 30 Jun 2024.', [period], mask=True) is None


@pytest.mark.parametrize('status,accepted', [('unaudited', True), ('audited', False), ('unknown', False)])
def test_normalized_calendar_date_keeps_its_own_explicit_assurance(status, accepted):
    from adaptive_document_agent.agent.retained_page_sources import _check_explicit_period_assurance
    rows = [_observation('Population', '30 Jun 2024', 100).model_copy(update={'audited_status': status})]
    text = bound_period_dates('At 30 Jun 2024 (unaudited), population was 100.', [rows[0].period])
    if accepted:
        _check_explicit_period_assurance(text, rows)
    else:
        with pytest.raises(ValueError, match='no bound row explicitly marked unaudited'):
            _check_explicit_period_assurance(text, rows)
