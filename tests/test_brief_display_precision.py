"""Fallback summaries deduplicate exact facts and reveal rounded differences."""

from copy import deepcopy

import pytest

from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import ChartPlan, PresentationSlide
from adaptive_document_agent.services.executive_brief import (
    _brief_chart_signature, _brief_fact_for_chart, display_brief,
)
from tests.test_p0_composition import observation, result_for


def _series(name, values, *, unit="currency", raw_unit="USD", page=3):
    items = [observation(name + str(i), "Revenue", value, f"FY{2023+i}", unit=unit)
             for i, value in enumerate(values)]
    for item in items:
        item.raw_unit = raw_unit
        item.validation_status = "valid"
        item.evidence[0].page = page
    chart = ChartPlan(id=name, title="Revenue", chart_type="line", question="What changed?",
                      observation_ids=[item.id for item in items])
    return items, chart


def _result(first, second):
    items_a, chart_a = first
    items_b, chart_b = second
    result = result_for(items_a + items_b, [chart_a, chart_b])
    result.presentation_plan.slides = [PresentationSlide(
        id=chart.id, slide_type="analysis", title="Revenue", section_id="performance",
        chart_ids=[chart.id]) for chart in (chart_a, chart_b)]
    return result


def test_per_unit_decimal_spelling_never_adds_binary_float_precision():
    items, chart = _series("price", [1234567.89, 1234568.89], raw_unit="USD/unit")
    before = deepcopy(items)
    fact = _brief_fact_for_chart(chart, DocumentIndex(items))
    assert "USD 1,234,567.89/unit" in fact[0]
    assert "USD 1,234,568.89/unit" in fact[0]
    assert "999999" not in fact[0]
    assert items == before


def test_source_unaudited_status_is_explained_beside_the_summary_period():
    items, chart = _series("cash", [1200000, 1700000, 2200000])
    items[-1].audited_status = "unaudited"
    text, _ = _brief_fact_for_chart(chart, DocumentIndex(items))
    assert "FY2025 (unaudited)" in text
    assert "FY2025*" not in text
    assert "FY2023 (unaudited)" not in text


def test_exact_corroborating_series_merges_once_with_both_sources():
    result = _result(_series("a", [1200000, 1700000, 2200000], page=3),
                     _series("b", [1200000, 1700000, 2200000], page=9))
    before = deepcopy(result.model_dump())
    _, summaries = display_brief(result)
    assert len(summaries) == 1
    assert summaries[0].text.count("Revenue:") == 1
    assert summaries[0].pages == [3, 9]
    assert result.model_dump() == before


@pytest.mark.parametrize("second_values, expected", [
    ([1240000, 1740000, 2240000], ["1,200,000", "1,240,000", "2,200,000", "2,240,000"]),
    ([1200000, 1800000, 2200000], ["1,700,000", "1,800,000"]),
])
def test_rounded_or_endpoint_only_copy_cannot_hide_different_source_values(second_values, expected):
    result = _result(_series("a", [1200000, 1700000, 2200000], page=3),
                     _series("b", second_values, page=9))
    before = deepcopy(result.model_dump())
    _, summaries = display_brief(result)
    assert len(summaries) == 1
    assert summaries[0].text.count("Revenue:") == 2
    assert all(value in summaries[0].text for value in expected)
    assert summaries[0].pages == [3, 9]
    assert result.model_dump() == before


@pytest.mark.parametrize("field,value", [
    ("ifrs_status", "non-IFRS"), ("raw_unit", "USD thousand"),
    ("raw_value", "1,200,000.00"), ("period_basis", "calendar_year"),
    ("value", -1200000), ("category_dimensions", {"product": "Service"}),
])
def test_summary_identity_preserves_reporting_basis_units_precision_sign_and_category(field, value):
    items, chart = _series("a", [1200000, 1700000, 2200000])
    index = DocumentIndex(items)
    original = _brief_chart_signature(chart, index)
    changed = deepcopy(items)
    setattr(changed[0], field, value)
    assert _brief_chart_signature(chart, DocumentIndex(changed)) != original
