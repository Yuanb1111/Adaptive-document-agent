import pytest
from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.scoped_narrative_values import scoped_value_errors
from tests.test_p0_composition import observation


@pytest.mark.parametrize('unit', ['RMB in thousands', 'USD millions', 'cubic metres'])
def test_parenthesized_source_unit_header_cannot_steal_endpoint_subject(unit):
    own = observation('own', 'Stored amount', 120)
    other = observation('other', 'Delivered amount', 90)
    header = observation('header', f'({unit})', 88)
    header.raw_unit = unit
    header.metric_canonical = None
    slide = PresentationSlide(id='s', slide_type='analysis', title='Stored amount',
        message=f'Stored amount was 100 {unit} and rose to 120.')
    assert not scoped_value_errors(slide, [own, other], [own, other, header])
    slide.message = f'Stored amount was 100 {unit} and rose to 90.'
    assert scoped_value_errors(slide, [own, other], [own, other, header])


def test_parenthetical_measure_without_matching_unit_is_not_ignored():
    own = observation('own', '(Stored amount)', 120)
    other = observation('other', 'Delivered amount', 90)
    slide = PresentationSlide(id='s', slide_type='analysis', title='Review',
        message='Stored amount rose to 90.')
    assert scoped_value_errors(slide, [own, other])
