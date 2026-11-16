"""A reported price keeps its source numerator scale, currency and denominator."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models import Observation
from adaptive_document_agent.agent.presentation_insight_recovery import _numeric_support
from adaptive_document_agent.validation.presentation_numeric_evidence import mask_reported_currency_rates


def rate(basis='kg'):
    return Observation(id='rate',metric_original='Delivery charge',period='FY2020',
        raw_value='1.25',value=1250,unit='currency',raw_unit='USD in thousands/'+basis,
        currency='USD',unit_scale=1000,unit_family='currency',validation_status='valid',confidence=1,
        evidence=[dict(page=1,text='Original delivery-charge table.',extraction_method='table',confidence=1)])


@pytest.mark.parametrize('amount',[
    'USD 1.25 thousand/kg','USD 1250/kg','US$ 1.25 thousand per kg',
])
def test_rate_display_has_exact_source_unit_and_leaves_original_values_unchanged(amount):
    source=rate();before=deepcopy(source)
    text='Delivery charge was '+amount+' in FY2020.'
    assert _numeric_support(text,[source])
    masked,errors=mask_reported_currency_rates(text,[source])
    assert not errors and '1.25' not in masked and '1250' not in masked and len(masked)==len(text)
    assert source==before


@pytest.mark.parametrize('amount',[
    'EUR 1.25 thousand/kg','USD 1.25 million/kg','USD 1.26 thousand/kg',
    'USD 1.25 thousand/tonne','USD 1.25 thousand','USD 1.25 thousand/kg/hour',
    'USD 1.25 thousand/kg per hour','USD 1.25 thousand/kg²',
    '(USD 1.25 thousand)/kg','negative USD 1.25 thousand/kg',
])
def test_rate_cannot_borrow_other_currency_scale_value_sign_or_denominator(amount):
    assert not _numeric_support('Delivery charge was '+amount+' in FY2020.',[rate()])


def test_denominator_parameters_are_only_masked_as_exact_source_unit_metadata():
    source=rate('1000 units')
    valid='Delivery charge was USD 1.25 thousand/1000 units in FY2020.'
    assert _numeric_support(valid,[source])
    assert not mask_reported_currency_rates(valid,[source])[1]
    assert not _numeric_support(valid.replace('/1000 units','/100 units'),[source])
    assert not _numeric_support(valid+' There were 1000 deliveries.',[source])


def test_plain_monetary_total_cannot_supply_a_price_denominator():
    source=rate();source.raw_unit='USD in thousands'
    text='Delivery charge was USD 1.25 thousand/kg in FY2020.'
    assert not _numeric_support(text,[source])
    assert mask_reported_currency_rates(text,[source])[1]
