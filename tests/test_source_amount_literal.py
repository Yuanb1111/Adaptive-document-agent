"""Missing display scales must be corrected without deleting source amounts."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models import Observation
from adaptive_document_agent.services.source_amount_literal import source_amount_literal
from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support


def amount(**updates):
    return Observation.model_validate(dict(id='source', metric_original='Balance',
        raw_value='1,250', value=1250000, raw_unit='USD in thousands', unit='currency',
        currency='USD', unit_scale=1000, unit_family='currency', confidence=1, **updates))


@pytest.mark.parametrize('raw,value,scale,expected', [
    ('1,250', 1250000, 1000, 'USD 1,250 thousand'),
    ('(1,250)', -1250000, 1000, '(USD 1,250 thousand)'),
    ('-1,250', -1250000, 1000, 'USD -1,250 thousand'),
    ('12.50', 12500000, 10**6, 'USD 12.50 million'),
    ('2', 2*10**9, 10**9, 'USD 2 billion'),
    ('2', 2, 1, 'USD 2'),
])
def test_literal_preserves_raw_precision_sign_and_explicit_scale(raw,value,scale,expected):
    item=amount().model_copy(update=dict(raw_value=raw,value=value,unit_scale=scale))
    before=deepcopy(item.model_dump())
    assert source_amount_literal(item)==expected
    assert _numeric_support(expected,[item])
    assert item.model_dump()==before


@pytest.mark.parametrize('updates', [
    dict(currency=None), dict(value=None), dict(value=1250), dict(unit_scale=None),
    dict(unit_scale=10000), dict(unit_family='percentage'), dict(raw_value='about 1,250'),
    dict(raw_unit='USD thousand per unit'), dict(raw_value='(1,250)'),
])
def test_no_invented_unit_scale_value_or_denominator(updates):
    assert source_amount_literal(amount().model_copy(update=updates)) is None


def test_bad_unit_hint_never_grants_numeric_approval_or_lends_another_currency():
    item=amount()
    errors=[]
    assert not _numeric_support('Balance was USD 1,250.',[item],diagnostics=errors)
    assert any('USD 1,250 thousand' in e and 'rather than deleting' in e for e in errors)
    assert _numeric_support('Balance was USD 1,250 thousand.',[item])
    for claim in ['Balance was USD 1,251.', 'Balance was RMB 1,250.']:
        errors=[]
        assert not _numeric_support(claim,[item],diagnostics=errors)
        assert not any('exact supported amount spelling' in e for e in errors)


def test_author_packet_carries_full_source_unit_alongside_unchanged_raw_fields():
    from tests.test_retained_analysis_v216 import _linked_result
    from adaptive_document_agent.agent.retained_page_sources import page_sources
    result=_linked_result()
    result.observations=[amount().model_copy(update=dict(
        table_id='table',evidence=result.observations[0].evidence))]
    item=result.observations[0]
    linked={'finding':(result.insights[0],{item.id},None)}
    row,=page_sources(result,linked)['source_rows']
    assert (row['value'],row['unit'],row['amount_literal'])==(
        '1,250','USD in thousands','USD 1,250 thousand')


def test_amount_failure_does_not_hide_direction_failure_or_approve_the_page():
    from tests.test_retained_analysis_v216 import _linked_result
    from adaptive_document_agent.agent.retained_analysis import (
        findings, selection_context, RetainedAnalysisSelection)
    from adaptive_document_agent.agent.retained_page_sources import (
        RetainedPage, page_bindings, validate_authored_pages, AuthoredPageErrors)
    result=_linked_result()
    insight,primary,_=next(iter(findings(result,allow_new_copy=True).values()))
    context=selection_context(result,source_authoring=True)
    page=RetainedPage(title='Revenue',message=(
        f'Revenue rose through FY2025 and was RMB {result.observations[0].raw_value}.'))
    selection=RetainedAnalysisSelection(decisions=[dict(insight_id=insight.id,
        decision='include',reason='Synthetic test.',page=page)],ordered_insight_ids=[insight.id])
    with pytest.raises(ValueError,match='Unbound typed amount'):
        page_bindings(page,insight,primary,context,result)
    with pytest.raises(AuthoredPageErrors) as caught:
        validate_authored_pages(selection,context,result)
    errors=caught.value.by_insight[insight.id]
    assert any('Unbound typed amount' in e for e in errors)
    assert any('temporal direction needs explicit start and end' in e for e in errors), errors
