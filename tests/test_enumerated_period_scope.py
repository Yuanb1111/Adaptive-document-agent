"""Explicit listed dates require every adjacent comparison, never endpoint guessing."""
import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.enumerated_period_scope import explicit_period_list, enumerated_segments
from adaptive_document_agent.validation.direction_scope import inherited_period_range
from tests.test_retained_analysis_v216 import _linked_result

DATES=['2021-12-31','2022-12-31','2023-12-31','2024-06-30','2024-10-31']


def rows(values=(270,190,175,146,116)):
    template=_linked_result().observations[0]
    return [template.model_copy(update=dict(id=f'row-{i}',metric_original='Assets',
        metric_canonical='Assets',period=date,period_type='balance_sheet_date',period_basis='generic',
        value=value,raw_value=str(value))) for i,(date,value) in enumerate(zip(DATES,values))]


def text(dates=None):
    dates=dates or DATES[:4]
    return ('For the Assets balances as of '+', '.join(dates[:-1])+' and '+dates[-1]+
            ', the filing attributes the decrease to redemption of deposits, partially offset by purchases.')


def test_exact_enumeration_is_inherited_and_each_adjacent_pair_is_checked():
    claim=text()
    scope,error=inherited_period_range(claim,claim.index('decrease'),'the filing attributes the decrease')
    assert not error and scope.startswith('as of 2021-12-31')
    segments=enumerated_segments(scope,rows())
    assert [[o.period for o in pair] for pair in segments]==[DATES[i:i+2] for i in range(3)]
    slide=PresentationSlide(id='listed',title='Assets',slide_type='analysis',message=claim)
    assert not ClaimValidator().validate_slide(slide,rows())
    issues=ClaimValidator().validate_slide(slide,rows((270,190,210,146,116)))
    assert any(e.code=='directional_contradiction' for e in issues)


@pytest.mark.parametrize('dates',[
    [DATES[0],DATES[2],DATES[3]],
    [DATES[0],DATES[2],DATES[1]],
    [DATES[0],DATES[1],DATES[1]],
    [DATES[0],DATES[1],'2028-06-30'],
    ['2021','2022',DATES[2]],
])
def test_list_cannot_supply_missing_duplicate_reversed_or_unbound_dates(dates):
    assert enumerated_segments(text(dates),rows())==[]
    slide=PresentationSlide(id='bad',title='Assets',slide_type='analysis',message=text(dates))
    assert ClaimValidator().validate_slide(slide,rows())


@pytest.mark.parametrize('claim',[
    'For 2021-12-31, 2022-12-31 and 2023-12-31, balances declined.',
    text()+' The separate date was 2028-01-01.',
    text().replace(' and 2024-06-30',' or 2024-06-30'),
])
def test_bare_dates_alternative_dates_and_unowned_dates_do_not_form_scope(claim):
    assert explicit_period_list(claim) is None
