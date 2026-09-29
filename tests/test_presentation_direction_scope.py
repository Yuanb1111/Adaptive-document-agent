"""Directional display copy carries the exact supported comparison bounds."""

from adaptive_document_agent.services.presentation_trajectory import scoped_direction_title
from test_presentation_key_figures import _result


def test_directional_title_uses_plotted_endpoints_without_changing_claim():
    result = _result()
    chart = result.charts[0]
    index = {item.id: item for item in result.observations}
    assert scoped_direction_title('Reported measure increased', [chart], index) == (
        'Reported measure increased (FY2022–FY2023)'
    )
    assert scoped_direction_title('Reported measure increased (FY2022–FY2023)', [chart], index) == (
        'Reported measure increased (FY2022–FY2023)'
    )
    assert scoped_direction_title('Reported measure', [chart], index) == 'Reported measure'


def test_directional_title_requires_one_compatible_shared_scope():
    result = _result()
    index = {item.id: item for item in result.observations}
    result.observations[3].period = '6M2023'
    result.observations[3].period_basis = '6M'
    result.observations[3].period_type = 'interim_flow'
    assert scoped_direction_title('Reported measure declined', result.charts[:2], index) == (
        'Reported measure declined'
    )
