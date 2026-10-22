"""A measured chart-pair sidebar can avoid unnecessary evidence continuations."""
import json

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import ChartPlan, PresentationSlide, PresentationVisualBlock, PresentationTheme
from adaptive_document_agent.services.slide_compositor import (
    compose_geometry, _ChartCapacityError, _render_composed_slide,
    render_composed_slide, validate_composed_geometry,
)
from tests.test_chart_capacity_pagination import _deck
from tests.test_p0_composition import observation, result_for


def _case(extra_rows=1):
    records, charts = [], []
    for n, metric in enumerate(('Annual production and maintenance expenditure',
                                 'Annual production and maintenance expenditure ratio %')):
        points = [observation(f'chart-{n}-{year}', metric, value, f'FY{year}',
            unit='percent' if n else 'currency') for year, value in zip((2021, 2022, 2023), (34, 27, 28) if n else (47, 52, 70))]
        records.extend(points)
        charts.append(ChartPlan(id=f'chart-{n}', title=metric, question='Reported values',
            chart_type='line', observation_ids=[o.id for o in points], source_pages=[3]))
    support = [observation(f'support-{i}', f'Total expenditure ratio {i}', 29 + i, 'FY2023', unit='percent')
               for i in range(extra_rows)]
    records.extend(support)
    plan = PresentationSlide(id='activity', slide_type='analysis', theme_id='activity', layout='two_up',
        title='Production expenditure and ratios, FY2021-FY2023',
        section_title='Production expenditure and ratios, FY2021-FY2023',
        message='How did annual expenditure and expenditure ratios change from FY2021 to FY2023?',
        chart_ids=[c.id for c in charts], source_pages=[3], visual_blocks=[
            PresentationVisualBlock(role='table', observation_ids=[o.id for o in support])])
    result = result_for(records, charts, plan)
    result.presentation_plan.themes = [PresentationTheme(id='activity', title=plan.title,
        question=plan.message, rationale='Compare selected source records', chart_ids=plan.chart_ids,
        caveats=['Annual expenditure ratio: annual expenditure divided by annual total operating expenditure.',
                 'Annual ratio and cumulative ratio have different source scopes.',
                 'The source does not identify an audit qualification for these annual observations.'])]
    return result, plan, charts, support


def test_sidebar_geometry_retains_minimum_chart_widths_and_disjoint_support():
    geometry = compose_geometry(12.6, 7.09, 1.7, 2, layout='two_up', has_support=True,
        has_commentary=True, support_sidebar=True, chart_min_widths=[2.4, 3.0])
    assert all(r.h > 4 for r in geometry.charts)
    assert geometry.charts[0].w >= 2.4 and geometry.charts[1].w >= 3.0
    assert geometry.support.x > geometry.charts[-1].x + geometry.charts[-1].w
    assert geometry.commentary.y > geometry.support.y + geometry.support.h
    with pytest.raises(_ChartCapacityError):
        compose_geometry(12.6, 7.09, 1.7, 2, layout='two_up', has_support=True,
            has_commentary=False, support_sidebar=True, chart_min_widths=[5.0, 5.0])


def test_chart_pair_and_complete_table_fit_one_page_without_changing_caption_or_evidence():
    result, plan, charts, support = _case()
    before = result.model_dump()
    index = DocumentIndex(result.observations)
    with pytest.raises(_ChartCapacityError):
        _render_composed_slide(_deck(), plan, charts, result, index)
    deck = _deck()
    pages = render_composed_slide(deck, plan, charts, result, index)
    assert len(pages) == 1
    native = [s for s in pages[0].shapes if s.has_chart]
    assert [s.name for s in native] == [f'chart:{c.id}' for c in charts]
    assert [list(s.chart.series[0].values) for s in native] == [[47, 52, 70], [34, 27, 28]]
    assert all(s.height.inches >= 1.8 for s in native)
    tables = [s for s in pages[0].shapes if s.has_table]
    assert len(tables) == 1 and support[0].id in tables[0].name
    from adaptive_document_agent.services.presentation_trajectory import supported_subtitle
    caption = supported_subtitle(plan, charts[:1], index)
    assert caption in '\n'.join(s.text for s in pages[0].shapes if s.has_text_frame)
    notes = json.loads(pages[0].notes_slide.notes_text_frame.text)
    assert {o['id'] for o in notes['observations']} == {o.id for o in result.observations}
    assert result.model_dump() == before
    validate_composed_geometry(deck)


def test_overflowing_sidebar_is_discarded_without_duplicate_charts_or_lost_table_rows():
    result, plan, charts, support = _case(extra_rows=18)
    deck = _deck()
    sentinel = deck.slides.add_slide(deck.slide_layouts[0])
    before = result.model_dump()
    pages = render_composed_slide(deck, plan, charts, result, DocumentIndex(result.observations))
    assert len(pages) > 1 and deck.slides[0] is sentinel
    assert len(deck.slides) == len(pages) + 1
    assert [s.name for page in pages for s in page.shapes if s.has_chart] == [f'chart:{c.id}' for c in charts]
    ids = [oid for page in pages for s in page.shapes if s.has_table
           for oid in s.name.removeprefix('table:').split(',')]
    assert sorted(ids) == sorted(o.id for o in support)
    assert result.model_dump() == before
    validate_composed_geometry(deck)
