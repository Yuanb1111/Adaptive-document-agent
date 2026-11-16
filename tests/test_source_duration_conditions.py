"""Equivalent source boundary notation never changes comparator, count or unit."""
import pytest

from adaptive_document_agent.services.source_duration_conditions import mask_worded_duration_conditions
from adaptive_document_agent.agent.reported_source_context import (
    QualifiedSourceCopy,reported_source_components,qualified_source_statement)
from adaptive_document_agent.models.executive_brief import BriefQuote


@pytest.mark.parametrize('wording',[
    'more than two years','more-than-two-years','older-than-two-year','over-two-year',
])
def test_equivalent_gt_boundary_spelling_retains_source_proof(wording):
    proof='Management assessed cases with an age of more than 2 years.'
    item=QualifiedSourceCopy(scope='the cases discussion',
        description='describes management’s assessment of the '+wording+' category',quote=BriefQuote(page=1,text=proof))
    statement=qualified_source_statement(item)
    _,parts=reported_source_components('The source reports levels. '+statement,[item.quote],declared=[item])
    assert parts==[statement] and item.quote.text==proof


@pytest.mark.parametrize('proof,copy,accepted',[
    ('more than 2 years','over-two-year',True),
    ('at least 2 years','over-two-year',False),
    ('less than 2 years','under-two-year',True),
    ('at most 2 years','under-two-year',False),
    ('no more than 2 years','not-more-than-two-years',True),
    ('no more than 2 years','more-than-two-years',False),
    ('at least 2 years','no-less-than-two-year',True),
    ('more than 2 months','more-than-two-years',False),
    ('more than 3 years','more-than-two-years',False),
    ('more than 2 years','not-older-than-two-years',False),
    ('within 1 year','within-one-year',True),
    ('within 1 year','within-two-years',False),
    ('over -2 years','over-two-years',False),
])
def test_operator_count_unit_and_negation_are_exact(proof,copy,accepted):
    masked=mask_worded_duration_conditions('The '+copy+' category.',proof)
    assert (copy not in masked)==accepted


def test_boundary_mask_does_not_authorize_a_measured_duration_or_numeric_copy():
    proof='Cases with an age of more than 2 years were assessed.'
    for text in ['The duration increased by two years.','The boundary is more than 2 years.']:
        assert mask_worded_duration_conditions(text,proof)==text
