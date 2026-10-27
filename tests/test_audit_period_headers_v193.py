"""Shared date notation is literal evidence, never independent assurance approval."""
from copy import deepcopy

import pytest

from adaptive_document_agent.agent.report_audit_scope import (
    AuditScopeDraft, AuditScopeReview, _context, _period_in_header, _validate,
    review_report_audit_scope, reviewed_audit_bindings,
)
from adaptive_document_agent.agent.report_audit_batches import validate_review
from tests.test_report_audit_scope_v174 import Gateway, fixture
from tests.test_audit_counterpart_v174 import models


SHARED_LIST = 'As at 31 December\n2021, 2022, 2023 and 30 June 2024'
TIERS = ('                   As at 31 December\n'
         '                                   As at 30 June\n'
         '        Notes      2021    2022     2023    2024')


@pytest.mark.parametrize('period', ['2021-12-31', '2022-12-31', '2023-12-31', '2024-06-30'])
@pytest.mark.parametrize('header', [SHARED_LIST, TIERS,
    'As at December 31, 2021, 2022 and 2023 and June 30, 2024'])
def test_complete_shared_date_notation_has_literal_components(period, header):
    assert _period_in_header(period, header)


@pytest.mark.parametrize('period,header', [
    ('2024-12-31', SHARED_LIST), ('2022-06-30', SHARED_LIST),
    ('2020-12-31', TIERS), ('2023-06-29', TIERS),
    ('2022-12-31', '31 December 2021. Revenue grew in 2022.'),
    ('2022-12-31', 'As at 31 December\nRevenue for 2022'),
    ('2022-12-31', 'As at 31 December\n2021'),
    ('2023-02-29', 'As at 29 February 2023'),
    ('2024-06-30', 'As at 30 June 20240'),
    ('2024-06-30', '12024-06-30'),
    ('2024-06-30', 'As at 31 December 2024 and 30 June 2023'),
])
def test_unrelated_year_invalid_date_or_missing_header_is_not_support(period, header):
    assert not _period_in_header(period, header)


@pytest.mark.parametrize('period,header', [
    ('2024-02-29', 'As at 29 February 2024'),
    ('2024-06-30', 'As at 2024-06-30'),
    ('FY2023', 'Years ended 31 December 2021, 2022 and 2023'),
    ('6M2024', 'Six months ended 30 June 2024'),
])
def test_complete_dates_and_flow_periods_remain_supported(period, header):
    assert _period_in_header(period, header)


def snapshot_fixture(header=TIERS, period='2022-12-31'):
    result, binding = fixture()
    for observation in result.observations:
        observation.period = period
    old = binding['header_quote']['text']
    result.document.pages[4].text = result.document.pages[4].text.replace(old, header)
    binding.update(period=period, header_quote=dict(page=5, text=header))
    return result, binding


@pytest.mark.parametrize('header', [TIERS, SHARED_LIST])
def test_date_fix_reaches_independent_review_without_changing_source_or_accepting_rejection(header):
    result, binding = snapshot_fixture(header)
    original = deepcopy((result.document, result.observations))
    gateway = Gateway(binding, accepted=False)
    with pytest.raises(ValueError, match='Wrong scope'):
        review_report_audit_scope(gateway, result)
    assert [call[0] for call in gateway.calls] == [AuditScopeDraft, AuditScopeReview] * 2
    assert not reviewed_audit_bindings(result)
    assert (result.document, result.observations) == original
    for _, messages, _ in gateway.calls:
        assert 'never proof of column ownership' in messages[0]['content']


def test_shared_components_do_not_replace_required_independent_source_proof():
    # Ambiguous flattened tiers expose components only; no code infers ownership.
    result, binding = snapshot_fixture(period='2022-06-30')
    draft, review = models(binding, None)
    _validate(draft, _context(result))
    with pytest.raises(ValueError, match='independently covered source table'):
        validate_review(draft, review, _context(result))


@pytest.mark.parametrize('field,value', [('source_raw_value', '120,463'),
    ('source_currency', 'USD'), ('period', '2020-12-31')])
def test_date_components_never_override_other_binding_errors(field, value):
    result, binding = snapshot_fixture()
    binding[field] = value
    gateway = Gateway(binding)
    with pytest.raises(ValueError):
        review_report_audit_scope(gateway, result)
    assert all(call[0] is AuditScopeDraft for call in gateway.calls)
    assert not reviewed_audit_bindings(result)


@pytest.mark.parametrize('prefix,suffix', [
    ('', '\nRMB’000 RMB’000 RMB’000 RMB’000'),
    ('STATEMENT OF FINANCIAL POSITION\n', '\nRMB’000 RMB’000 RMB’000 RMB’000\n(Unaudited)'),
])
def test_complete_literal_header_can_retain_surrounding_title_units_and_qualifiers(prefix, suffix):
    header = prefix + TIERS + suffix
    assert _period_in_header('2022-12-31', header)
    assert _period_in_header('2024-06-30', header)
    assert not _period_in_header('2020-12-31', header)
    assert not _period_in_header('2022-06-29', header)


@pytest.mark.parametrize('intervening', ['Revenue 500', 'A different table follows.', 'RMB’000 RMB’000'])
def test_subheader_scan_never_bridges_intervening_source_content(intervening):
    header = f'As at 31 December\n{intervening}\nNotes 2021 2022 2023\nRMB’000'
    assert not _period_in_header('2022-12-31', header)
