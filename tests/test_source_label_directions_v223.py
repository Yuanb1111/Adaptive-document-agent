"""A source metric name is not itself a temporal predicate."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from tests.test_topic_coverage_review import _observation


def observations(label, *, split):
    rows = [_observation(label, period, value) for period, value in
            [('FY2021', 9_500), ('FY2022', 146_942), ('FY2023', -187_427)]]
    if split:
        for row in rows:
            row.parent_section = '..... NET INCREASE/(DECREASE) IN'
            row.dimensions['section'] = row.parent_section
    return rows


@pytest.mark.parametrize('metric', ['Cash and cash equivalents', 'Available volunteer hours'])
@pytest.mark.parametrize('split', [True, False])
def test_literal_direction_words_stay_inside_source_label_but_predicate_is_checked(metric, split):
    source_label = f'Net increase/(decrease) in {metric}'
    rows = observations(metric if split else source_label, split=split)
    retained = deepcopy(rows)
    slide = PresentationSlide(id='s', slide_type='analysis', title=source_label,
        message=f'{source_label} decreased from 146,942 in FY2022 to (187,427) in FY2023. '
                f'{source_label} was 9,500 in FY2021.')
    assert not ClaimValidator().validate_slide(slide, rows)
    slide.message = slide.message.replace('decreased from', 'increased from')
    issues = ClaimValidator().validate_slide(slide, rows)
    assert any(i.code == 'directional_contradiction' and i.offending_direction == 'increased' for i in issues)
    slide.message = f'{source_label} decreased through FY2023.'
    assert any(i.code == 'direction_scope_ambiguous' for i in ClaimValidator().validate_slide(slide, rows))
    assert rows == retained


def test_a_named_metric_does_not_hide_another_subjects_predicate():
    metric = 'Net increase/(decrease) in available volunteer hours'
    rows = observations(metric, split=False)
    slide = PresentationSlide(id='s', slide_type='analysis', title='Volunteer activity',
        message=f'{metric} was 9,500 in FY2021. '
                'Available volunteer hours increased from FY2022 to FY2023.')
    # A non-exact label must not erase the actual asserted increase.
    assert ClaimValidator().validate_slide(slide, rows)
