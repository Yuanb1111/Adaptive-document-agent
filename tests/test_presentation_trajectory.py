"""Displayed analysis captions stay within selected chart evidence."""

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.services.presentation_trajectory import supported_subtitle
from tests.test_pptx_export import _result


def test_analytical_question_gets_literal_periods_and_values():
    result = _result()
    slide = PresentationSlide(id='question', slide_type='analysis', title='Revenue',
                              message='How did revenue change?', chart_ids=['chart-1'])
    text = supported_subtitle(slide, result.charts, DocumentIndex(result.observations))
    assert 'FY2023 RMB 267.0m' in text and 'FY2025 RMB 521.7m' in text
    assert '?' not in text


def test_directional_claim_with_reversal_shows_the_turning_value():
    result = _result()
    result.observations[1].value = 600_000_000
    slide = PresentationSlide(id='reversal', slide_type='analysis', title='Revenue growth',
                              message='Revenue increased throughout.', chart_ids=['chart-1'])
    text = supported_subtitle(slide, result.charts, DocumentIndex(result.observations))
    assert 'FY2024 RMB 600m' in text
    assert 'increased throughout' not in text
    assert slide.message == 'Revenue increased throughout.'
