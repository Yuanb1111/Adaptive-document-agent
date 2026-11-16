"""Calendar formatting cannot alter comparison scope or original evidence."""
from copy import deepcopy
import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.direction_scope import _period_index
from adaptive_document_agent.validation.calculated_change_label import labelled_change_supported
from tests.test_topic_coverage_review import _observation


@pytest.mark.parametrize('periods',[
    ['31 Dec 2021','31 Dec 2022','31 Dec 2023'],
    ['December 31, 2021','December 31, 2022','December 31, 2023'],
    ['2021-12-31','2022-12-31','2023-12-31'],
])
def test_direction_uses_exact_calendar_identity_and_keeps_raw_labels(periods):
    rows=[_observation('Program balance',p,v) for p,v in zip(periods,[100,120,150])]
    before=deepcopy(rows)
    assert _period_index('2021-12-31',rows)==0
    assert _period_index('2023-12-31',rows)==2
    assert _period_index('2023-06-30',rows) is None
    assert _period_index('FY2023',rows) is None
    slide=PresentationSlide(id='generic',slide_type='analysis',title='Program balance',
        message='Program balance rose from 2021-12-31 to 2023-12-31.')
    assert not ClaimValidator().validate_slide(slide,rows)
    slide.message=slide.message.replace('rose','declined')
    assert ClaimValidator().validate_slide(slide,rows)
    assert rows==before


def test_exact_calendar_aliases_do_not_resolve_ambiguous_duplicate_endpoints():
    rows=[_observation('Program balance',p,v) for p,v in
          [('31 Dec 2021',100),('2021-12-31',200),('31 Dec 2023',300)]]
    assert _period_index('2021-12-31',rows) is None


def test_calculated_rate_matches_spelled_input_dates_without_changing_catalog():
    catalog=[dict(kind='percentage_change',unit='percent',value=50,metric='Program balance',
                  periods=['31 Dec 2021','31 Dec 2023'])]
    before=deepcopy(catalog)
    prefix='Calculated change: '
    assert labelled_change_supported(prefix+'50% from 2021-12-31 to 2023-12-31.',prefix,'50',catalog)
    assert not labelled_change_supported(prefix+'50% from 2021-12-31 to 2023-06-30.',prefix,'50',catalog)
    assert catalog==before


@pytest.mark.parametrize('spelling',[
    'from 100 units in 6M2021 (unaudited) to 120 units in 6M2022',
    'from 6M2021 (unaudited) to 6M2022',
    'from 100 units as of 6M2021 (unaudited) to 120 units as of 6M2022',
])
def test_assurance_annotation_does_not_hide_an_explicit_comparison_start(spelling):
    rows=[_observation('Programme deliveries',p,v,basis='6M') for p,v in
          [('6M2021',100),('6M2022',120),('6M2023',90)]]
    rows[0].audited_status='unaudited'
    before=deepcopy(rows)
    slide=PresentationSlide(id='generic',slide_type='analysis',title='Programme deliveries',
        message='Programme deliveries rose '+spelling+'.')
    assert not ClaimValidator().validate_slide(slide,rows)
    slide.message=slide.message.replace('rose','fell')
    assert ClaimValidator().validate_slide(slide,rows)
    slide.message='Programme deliveries rose '+spelling.replace('6M2022','6M2024')+'.'
    assert ClaimValidator().validate_slide(slide,rows)
    assert rows==before


@pytest.mark.parametrize('tail,valid',[
    ('rose from FY2022 to FY2023',True),
    ('fell from FY2022 to FY2023',False),
    ('rose from FY2022 to FY2024',False),
    ('unknown defects rose from FY2022 to FY2023',False),
])
def test_repeated_dated_predicate_inherits_only_its_explicit_shared_subject(tail,valid):
    rows=[_observation('Programme deliveries',p,v) for p,v in
          [('FY2021',100),('FY2022',120),('FY2023',150)]]
    slide=PresentationSlide(id='generic',slide_type='analysis',title='Programme deliveries',
        message='Programme deliveries rose from FY2021 to FY2022 and '+tail+'.')
    assert (not ClaimValidator().validate_slide(slide,rows))==valid
