"""Day-first report dates retain their exact source column and closing date."""
import pytest

from adaptive_document_agent.agent.brief_audit_scope import audit_status_errors
from adaptive_document_agent.agent.brief_period_clarification import (
    original_period_identities, quantity_text_with_bound_dates,
)
from tests.test_brief_audit_scope_v146 import _case


@pytest.mark.parametrize('date', ['30 June 2023', 'June 30, 2023'])
@pytest.mark.parametrize('position', ['before', 'after'])
def test_supported_date_orders_bind_the_same_source_column(date, position):
    result, brief = _case()
    qualification = f'unaudited {date}' if position == 'before' else f'{date} (unaudited)'
    brief.items[0].text = f'Programme fees were USD 1,250 thousand at {qualification}.'
    assert not audit_status_errors(brief.items[0], result)


@pytest.mark.parametrize('date', ['31 October 2023', '29 June 2023', '31 June 2023', '30 June 2024'])
@pytest.mark.parametrize('position', ['before', 'after'])
def test_other_or_invalid_dates_cannot_borrow_a_known_status(date, position):
    result, brief = _case()
    qualification = f'unaudited {date}' if position == 'before' else f'{date} (unaudited)'
    brief.items[0].text = f'Programme fees at {qualification}.'
    assert audit_status_errors(brief.items[0], result)


def test_same_year_columns_do_not_contaminate_a_complete_day_first_date():
    result, brief = _case()
    inventory = [dict(columns=[
        dict(period='2024-06-30', status='unknown', date_aliases=[]),
        dict(period='2024-10-31', status='unaudited', date_aliases=[]),
    ])]
    brief.items[0].text = 'Total indebtedness at 31 October 2024 (unaudited).'
    assert not audit_status_errors(brief.items[0], result, inventory=inventory)
    brief.items[0].text = 'Total indebtedness at 30 June 2024 (unaudited).'
    assert audit_status_errors(brief.items[0], result, inventory=inventory)
    inventory.append(dict(columns=[dict(period='2024-10-31', status='unknown', date_aliases=[])]))
    brief.items[0].text = 'Net current assets at 31 October 2024 (unaudited).'
    assert audit_status_errors(brief.items[0], result, inventory=inventory)


def test_day_first_flow_alias_preserves_duration_and_exact_closing_date():
    result, brief = _case()
    item = brief.items[0]
    item.text = 'Programme fees in the six months ended 30 June 2023 (unaudited).'
    assert not audit_status_errors(item, result)
    identities = original_period_identities(item, [], result=result)
    assert identities == {(6, '2023-06-30')}
    assert quantity_text_with_bound_dates('six months ended June 30, 2023', [], [],
                                         original_periods=identities) == ' '
    changed = 'six months ended 31 July 2023'
    assert quantity_text_with_bound_dates(changed, [], [], original_periods=identities) == changed
    item.text = 'Programme fees in the six months ended 31 June 2023 (unaudited).'
    assert audit_status_errors(item, result)
