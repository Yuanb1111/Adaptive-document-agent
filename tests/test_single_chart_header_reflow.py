"""A single chart can reclaim header space without losing source qualifications."""
import json

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import ChartPlan, PresentationSlide, PresentationTheme
from adaptive_document_agent.services.chart_space import composition_plot_height
from adaptive_document_agent.services.slide_compositor import (
    _ChartCapacityError, _render_composed_slide, render_composed_slide, validate_composed_geometry,
)
from tests.test_chart_capacity_pagination import _deck
from tests.test_p0_composition import observation, result_for


def _case(siblings=False):
    categories = ['Component Alpha', 'Component Beta', 'Component Gamma', 'Other components']
    records = [observation(f'mix-{year}-{n}', 'Category share', value, f'6M{year}',
                           unit='percent', category=category)
               for year in (2023, 2024)
               for n, (category, value) in enumerate(zip(categories, [40, 30, 20, 10]))]
    charts = [ChartPlan(id='mix', title='Category share', question='Reported category mix',
        chart_type='stacked_percent', series_dimension='segment',
        observation_ids=[o.id for o in records], source_pages=[3])]
    if siblings:
        for metric in ('Delivery volume', 'Average price'):
            values = [observation(f'{metric}-{year}', metric, value, f'6M{year}')
                      for year, value in ((2023, 20), (2024, 30))]
            records.extend(values)
            charts.append(ChartPlan(id=metric, title=metric, question='Reported values',
                chart_type='bar', observation_ids=[o.id for o in values], source_pages=[3]))
    plan = PresentationSlide(id='mix-topic', slide_type='analysis', theme_id='mix-topic',
        title='Category share of total output, delivery volume and ASP, 6M2023 to 6M2024',
        section_title='Category share of total output, delivery volume and ASP, 6M2023 to 6M2024',
        message='Reported category shares for the two separately disclosed interim periods 6M2023 and 6M2024.',
        layout='three_up' if siblings else 'single', chart_ids=[c.id for c in charts], source_pages=[3])
    result = result_for(records, charts, plan)
    notes = ['Comparisons retain the separately disclosed reporting periods and source measurement definitions.',
             'Other components include separately billed services, maintenance, training and technical support.',
             'Audit qualifications apply only to the source columns explicitly carrying the corresponding marker.',
             'The interim periods are presented separately from annual results.']
    result.presentation_plan.themes = [PresentationTheme(id=plan.theme_id, title=plan.title,
        question=plan.message, rationale='Compare retained evidence', chart_ids=plan.chart_ids, caveats=notes)]
    return result, plan, charts, categories, notes


@pytest.mark.parametrize('siblings', [False, True])
def test_header_reflow_retains_charts_complete_copy_and_source_notes(siblings):
    result, plan, charts, categories, notes = _case(siblings)
    before = result.model_dump()
    index = DocumentIndex(result.observations)
    with pytest.raises(_ChartCapacityError):
        _render_composed_slide(_deck(), plan, charts, result, index)
    deck = _deck()
    pages = render_composed_slide(deck, plan, charts, result, index)
    native = [s for page in pages for s in page.shapes if s.has_chart]
    assert [s.name for s in native] == [f'chart:{c.id}' for c in charts]
    assert composition_plot_height((0, 0, native[0].width.inches, native[0].height.inches),
                                   categories, compact=False) >= 2.0
    assert {s.name: list(s.values) for s in native[0].chart.series} == {
        category: [value] * 2 for category, value in zip(categories, [.4, .3, .2, .1])}
    visible = '\n'.join(s.text for page in pages for s in page.shapes if s.has_text_frame)
    assert plan.message in visible
    assert all(note in visible for note in notes)
    provenance = [json.loads(page.notes_slide.notes_text_frame.text) for page in pages]
    assert {o['id'] for record in provenance for o in record['observations']} == {o.id for o in result.observations}
    assert result.model_dump() == before
    validate_composed_geometry(deck)


def test_unfit_single_chart_still_fails_and_rolls_back_partial_pages(monkeypatch):
    result, plan, charts, _, _ = _case()
    import adaptive_document_agent.services.presentation_context_notes as context
    monkeypatch.setattr(context, 'slide_context_notes', lambda *a, **k: ['Complete qualification. ' * 600])
    deck = _deck()
    initial = len(deck.slides)
    with pytest.raises(_ChartCapacityError):
        render_composed_slide(deck, plan, charts, result, DocumentIndex(result.observations))
    assert len(deck.slides) == initial
