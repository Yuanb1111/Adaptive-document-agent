"""Native charts retain signs, source levels and actual reporting intervals."""

from copy import deepcopy
from datetime import date

import pytest

from adaptive_document_agent.models import ChartPlan
from adaptive_document_agent.services.pptx_export import _add_native_chart
from tests.test_p0_composition import observation
from tests.test_presentation_brief import blank_deck


@pytest.mark.parametrize("values", [(174.31, 241.01, 286.75), (34.3, 27.3, 28.1),
                                    (-41.76, -52.48, -103.28), (-12.4, 7.8), (0, 0)])
def test_axis_has_regular_ticks_and_preserves_every_point(values):
    items = [observation(str(i), "Recorded measure", v, f"FY{2020+i}", unit="percent")
             for i, v in enumerate(values)]
    before = deepcopy(items)
    deck = blank_deck()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    _add_native_chart(slide, ChartPlan(id="c", question="Reported values", chart_type="line", title="Recorded measure"), items, (.5, 1, 6, 4))
    chart = next(s.chart for s in slide.shapes if s.has_chart)
    axis = chart.value_axis
    assert list(chart.series[0].values) == list(values)
    assert axis.minimum_scale <= min(values) <= max(values) <= axis.maximum_scale
    assert (axis.minimum_scale / axis.major_unit) == pytest.approx(round(axis.minimum_scale / axis.major_unit))
    if min(values) >= 0:
        assert axis.minimum_scale == 0
    if max(values) <= 0 and min(values) < 0:
        assert axis.maximum_scale == 0
    assert items == before


def test_explicit_dates_use_calendar_spacing_and_keep_unequal_intervals():
    dates = ["2023-12-31", "2024-06-30", "2024-10-31"]
    items = [observation(str(i), "Recorded balance", 10+i, p) for i, p in enumerate(dates)]
    for item in items:
        item.period_type, item.as_of_date = "balance_sheet_date", item.period
    deck = blank_deck()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    _add_native_chart(slide, ChartPlan(id="c", question="Reported values", chart_type="line", title="Recorded balance"), items, (.5, 1, 6, 4))
    chart = next(s.chart for s in slide.shapes if s.has_chart)
    assert chart._chartSpace.xpath(".//c:dateAx")
    assert not chart._chartSpace.xpath(".//c:catAx")
    serials = [float(p.text) for p in chart._chartSpace.xpath(".//c:cat/c:numRef/c:numCache/c:pt/c:v")]
    assert serials[1] - serials[0] == (date.fromisoformat(dates[1]) - date.fromisoformat(dates[0])).days
    assert serials[2] - serials[1] != serials[1] - serials[0]
    assert float(chart._chartSpace.xpath(".//c:dateAx/c:scaling/c:min")[0].get("val")) < serials[0]
    assert float(chart._chartSpace.xpath(".//c:dateAx/c:scaling/c:max")[0].get("val")) > serials[-1]


def test_unknown_dates_remain_categories_without_inventing_a_calendar():
    from adaptive_document_agent.services.presentation_axes import explicit_date_categories
    item = observation("a", "Reported measure", 1, "FY2024")
    assert explicit_date_categories([item], ["FY2024"]) is None
