import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.dated_level_scope import dated_level_segments,explicit_dated_levels
from adaptive_document_agent.validation.direction_scope import inherited_period_range
from tests.test_enumerated_period_scope import rows,DATES


def claim(values=(116,146,175,190,270),style='at'):
    levels=[f'{v} ({d})' if style=='parentheses' else f'{v} {style} {d}'
            for v,d in zip(values,DATES)]
    return 'Assets were '+', '.join(levels[:-1])+' and '+levels[-1]+', increasing at each consecutive date.'


@pytest.mark.parametrize('style',['at','as of','in','parentheses'])
def test_dated_levels_share_scope_but_every_adjacent_direction_is_checked(style):
    text=claim(style=style)
    scope,error=inherited_period_range(text,text.index('increasing'),'increasing at each consecutive date')
    assert not error and dated_level_segments(scope,rows((116,146,175,190,270)))
    slide=PresentationSlide(id='levels',title='Assets',slide_type='analysis',message=text)
    assert not ClaimValidator().validate_slide(slide,rows((116,146,175,190,270)))
    # Endpoint growth cannot hide an intermediate decline in a listed sequence.
    slide.message=claim((116,175,146,190,270),style=style)
    assert any(e.code=='directional_contradiction'
               for e in ClaimValidator().validate_slide(slide,rows((116,175,146,190,270))))


@pytest.mark.parametrize('change',['swapped','missing','unbound','sign','duplicate'])
def test_raw_amounts_must_bind_to_their_own_exact_dates(change):
    text=claim()
    if change=='swapped':text=text.replace('116 at','146 at').replace('146 at 2022','116 at 2022')
    if change=='missing':text=text.replace('146 at 2022-12-31, ','')
    if change=='unbound':text=text.replace('2022-12-31','2028-12-31')
    if change=='sign':text=text.replace('146 at','(146) at')
    if change=='duplicate':text=text.replace('2022-12-31','2021-12-31')
    assert dated_level_segments(text,rows((116,146,175,190,270)))==[]
    slide=PresentationSlide(id='invalid',title='Assets',slide_type='analysis',message=text)
    assert ClaimValidator().validate_slide(slide,rows((116,146,175,190,270)))


@pytest.mark.parametrize('text',[
    claim()+' A different period is 2028-12-31.',
    claim().replace('146 at','Cash was 146 at'),
    'Assets rose from 116 at 2021-12-31 to 146 at 2022-12-31.',
])
def test_mixed_subjects_unowned_periods_and_existing_range_syntax_stay_separate(text):
    assert explicit_dated_levels(text) is None
