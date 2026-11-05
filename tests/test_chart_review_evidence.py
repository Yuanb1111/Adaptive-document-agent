import pytest
from pptx import Presentation
from adaptive_document_agent.models import ChartPlan
from adaptive_document_agent.services.chart_review_evidence import chart_scale_evidence
from adaptive_document_agent.services.pptx_export import _add_native_chart
from tests.test_p0_composition import observation


@pytest.mark.parametrize('scale,unit,raw,base,expected', [
    (1000, 'USD thousands', '120,000', 120000000, 120000),
    (1, 'USD', '120,000', 120000, 120),
])
def test_review_scale_matches_actual_native_chart_workbook(scale,unit,raw,base,expected):
    obs = observation('one','Balance',base)
    obs.raw_value, obs.raw_unit, obs.unit_scale, obs.currency = raw,unit,scale,'USD'
    chart = ChartPlan(id='c',title='Balance',question='Balance trend',chart_type='bar',observation_ids=['one'])
    before = obs.model_dump()
    packet = chart_scale_evidence(chart,[obs])
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    divisor, _ = _add_native_chart(slide,chart,[obs],(1,1,6,4))
    native = next(s.chart for s in slide.shapes if s.has_chart)
    assert native.series[0].values == (expected,)
    assert packet['native_ppt_scale']['values'][0]['value'] == expected
    assert packet['native_ppt_scale']['divisor'] == divisor
    assert packet['source_values'][0]['raw_value'] == raw
    assert packet['source_values'][0]['normalized_value'] == base
    assert obs.model_dump() == before


def test_scale_packet_does_not_assume_standard_scaling_for_composition():
    obs = observation('one','Balance',120)
    chart = ChartPlan(id='c',title='Balance',question='Mix',chart_type='doughnut',observation_ids=['one'])
    assert 'native_ppt_scale' not in chart_scale_evidence(chart,[obs])


def test_source_scale_requires_consistent_explicit_observation_units():
    from adaptive_document_agent.services.pptx_export import _display_scale
    a, b = observation('a','Balance',120000000), observation('b','Balance',130000000)
    for item in (a,b):
        item.raw_unit, item.unit_scale, item.currency = 'USD thousands', 1000, 'USD'
    assert _display_scale([a,b],130000000,prefer_source=True) == (1000,'thousands')
    assert _display_scale([a,b],130000000) == (1000000,'millions')
    b.unit_scale = 1
    assert _display_scale([a,b],130000000,prefer_source=True) == (1000000,'millions')
    b.unit_scale, b.raw_unit = 1000, None
    assert _display_scale([a,b],130000000,prefer_source=True) == (1000000,'millions')


def test_irregular_area_fallback_uses_category_spacing_for_native_columns():
    from pptx.enum.chart import XL_CHART_TYPE
    values = []
    for n, day in enumerate(['2021-12-31','2022-12-31','2023-12-31','2024-06-30','2024-10-31']):
        item = observation(str(n),'Balance',100000+n*1000)
        item.period = item.as_of_date = day
        item.period_type = 'balance_sheet_date'
        values.append(item)
    chart = ChartPlan(id='c',title='Balance',question='Trend',chart_type='area',
        observation_ids=[o.id for o in values])
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    _add_native_chart(slide,chart,values,(1,1,8,4))
    native = next(s.chart for s in slide.shapes if s.has_chart)
    assert native.chart_type == XL_CHART_TYPE.COLUMN_CLUSTERED
    assert not native._chartSpace.xpath('.//c:dateAx')
    assert len(native._chartSpace.xpath('.//c:catAx')) == 1
    assert len(native.plots[0].categories) == 5


def test_close_column_labels_keep_all_values_explicitly_on_category_points():
    from pptx.enum.chart import XL_DATA_LABEL_POSITION
    values = [observation(str(n),'Balance',v) for n,v in enumerate([150000,300000,110000,73000,81000])]
    for n, item in enumerate(values):
        item.period = f'FY{2020+n}'
    chart = ChartPlan(id='c',title='Balance',question='Trend',chart_type='bar',
        observation_ids=[o.id for o in values])
    deck=Presentation()
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    _add_native_chart(slide,chart,values,(1,1,6,4))
    native=next(s.chart for s in slide.shapes if s.has_chart)
    assert native.series[0].values == (150,300,110,73,81)
    assert all(p.data_label.position == XL_DATA_LABEL_POSITION.OUTSIDE_END for p in native.series[0].points)
    assert native.series[0].points[4].data_label.text_frame.paragraphs[0].runs[0].font.color.rgb == native.plots[0].data_labels.font.color.rgb
    assert [p.data_label.text_frame.text for p in native.series[0].points] == ['150','300','110','73','81']
    assert native.plots[0].has_data_labels
