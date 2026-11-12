import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.source_qualitative_shape import source_shape_noun
from tests.test_retained_analysis_v216 import _linked_result


def observations():
    result = _linked_result()
    inventory = [o.model_copy(update={'metric_original': 'Inventories', 'metric_canonical': 'Inventories'})
                 for o in result.observations]
    return [*inventory, *(o.model_copy(update={
        'id': o.id + '-other', 'metric_original': 'Cash', 'metric_canonical': 'Cash'})
        for o in result.observations)]


@pytest.mark.parametrize('shape', ['a dip and subsequent rise', 'an initial dip followed by a rebound'])
def test_source_nominal_shape_is_not_an_unbound_numeric_predicate(shape):
    rows = observations()
    text = f'The source describes {shape} in the provisions share of inventory costs across FY2023 to FY2025.'
    slide = PresentationSlide(id='qualitative', slide_type='analysis', title='Context', message=text, source_pages=[234])
    assert not ClaimValidator().validate_slide(slide, rows)
    slide.source_pages = []
    if 'rise' in shape:  # "rebound" was already outside the numeric predicate vocabulary.
        assert any(e.code == 'direction_scope_ambiguous'
                   for e in ClaimValidator().validate_slide(slide, rows))


@pytest.mark.parametrize('text', [
    'The source describes a dip and subsequent rise in the provisions share of inventory costs to 17%.',
    'The source describes a dip and subsequent rise in the provisions share of inventory costs worth RMB12 million.',
    'The source describes a dip and subsequent rise in the provisions share of inventory costs during 2028-10-31.',
    'The source says the provisions share of inventory costs declined from FY2023 to FY2025.',
    'The provisions share of inventory costs declined from FY2023 to FY2025.',
    'The source describes a rise in the provisions share of inventory costs.',
])
def test_numeric_dates_single_direction_and_verb_claims_keep_normal_binding(text):
    rows = observations()
    slide = PresentationSlide(id='numeric', slide_type='analysis', title='Context', message=text, source_pages=[234])
    assert any(e.code == 'direction_scope_ambiguous'
               for e in ClaimValidator().validate_slide(slide, rows))


def test_known_metrics_cannot_use_nominal_shape_to_disable_direction_checks():
    text = 'The source describes a dip and subsequent rise in revenue.'
    start = text.index('rise')
    assert not source_shape_noun(text, start, start + 4,
        metric_spans=[(text.index('revenue'), len(text) - 1)], periods=['FY2023', 'FY2025'])


def test_source_only_composition_uses_a_qualitative_shift_without_inventing_a_numeric_series():
    slide=PresentationSlide(id='composition',slide_type='analysis',title='Context',source_pages=[234],
        message='The source describes a shift toward long-aged gross inventory during the Track Record Period.')
    assert not ClaimValidator().validate_slide(slide,observations())


def test_ambiguous_word_feedback_identifies_the_exact_occurrence_and_clause():
    rows = observations()
    invalid = 'The source says the provisions share of inventory costs increased from FY2023 to FY2025.'
    text = 'Inventories increased from FY2023 to FY2025. ' + invalid
    slide = PresentationSlide(id='scoped', title='Inventories', slide_type='analysis', message=text,
                              source_pages=[234])
    errors = [e for e in ClaimValidator().validate_slide(slide, rows)
              if e.code == 'direction_scope_ambiguous' and getattr(e, 'target_component', '') == 'message']
    assert errors
    issue = errors[-1]
    assert invalid in issue.message
    assert text[issue.claim_start:issue.claim_end] == 'increased'
    assert issue.claim_start == text.rindex('increased')
