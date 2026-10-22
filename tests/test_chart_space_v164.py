"""Dense legends must not consume the useful plot area of an equal-width row."""
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import ChartPlan, PresentationSlide, PresentationVisualBlock
from adaptive_document_agent.services.chart_space import composition_plot_height, legend_rows
from adaptive_document_agent.services.slide_compositor import compose_geometry, render_composed_slide, validate_composed_geometry
from tests.test_chart_capacity_pagination import _deck
from tests.test_p0_composition import observation, result_for


def test_measured_widths_allocate_more_room_to_dense_chart_without_overlap():
    geometry = compose_geometry(12.6, 7.09, 1.45, 3, layout='three_up',
        has_support=False, has_commentary=False, chart_min_widths=[4.4, 2.4, 2.4])
    assert geometry.charts[0].w > geometry.charts[1].w
    assert geometry.charts[1].w == geometry.charts[2].w
    assert all(a.x + a.w < b.x for a,b in zip(geometry.charts, geometry.charts[1:]))
    labels = ['Category Alpha', 'Category Beta', 'Category Gamma', 'Category Delta']
    assert legend_rows(labels, 3, 11) > legend_rows(labels, 8, 11)
    assert composition_plot_height((0,0,3,2), labels, compact=False) < 1.6


def test_dense_chart_paginates_and_does_not_duplicate_later_plotted_values_as_tables():
    categories = ['Category Alpha', 'Category Beta', 'Category Gamma', 'Category Delta']
    obs = [observation(f'mix-{year}-{n}', 'Category share', value, f'FY{year}', unit='percent', category=category)
           for year in (2021,2022,2023) for n,(category,value) in enumerate(zip(categories,[40,30,20,10]))]
    charts = [ChartPlan(id='mix', title='Category share', question='Reported category mix',
        chart_type='stacked_percent', series_dimension='segment', observation_ids=[o.id for o in obs], source_pages=[3])]
    # After pagination this group looks like a compact source table; the
    # already-selected chart must remain a chart when its physical page splits.
    for item in obs:
        item.evidence[0].table_id = 'source-matrix'
    for n,metric in enumerate(['Production volume','Unit price']):
        values = [observation(f'm{n}-{year}',metric,value,f'FY{year}',unit='count')
                  for year,value in ((2021,20),(2022,30),(2023,40))]
        obs.extend(values)
        charts.append(ChartPlan(id=f'c{n}',title=metric,question='Reported values',chart_type='bar',
                               observation_ids=[o.id for o in values],source_pages=[3]))
    for o in obs:
        o.validation_status='valid'
    slide = PresentationSlide(id='dense',slide_type='analysis',layout='three_up',
        title='Category mix and reported production measures across the disclosed operating periods',
        message='Reported composition, production volume and unit price for FY2021, FY2022 and FY2023.',
        bullets=['The selected panels retain their separately disclosed measurement units and periods.'],
        chart_ids=[c.id for c in charts],source_pages=[3],
        visual_blocks=[PresentationVisualBlock(role='kpi',observation_ids=charts[-1].observation_ids)])
    result=result_for(obs,charts,slide);before=result.model_dump();deck=_deck()
    pages=render_composed_slide(deck,slide,charts,result,DocumentIndex(obs))
    native=[shape for page in pages for shape in page.shapes if shape.has_chart]
    assert len(pages)==2 and [shape.name for shape in native]==['chart:mix','chart:c0','chart:c1']
    assert not any(shape.has_table for page in pages for shape in page.shapes)
    first=native[0]
    assert composition_plot_height((0,0,first.width.inches,first.height.inches),categories,compact=False)>=2.0
    assert first.width > native[1].width
    assert {s.name:list(s.values) for s in first.chart.series} == {
        category:[value]*3 for category,value in zip(categories,[.4,.3,.2,.1])}
    assert result.model_dump()==before
    validate_composed_geometry(deck)
