"""Rates and prices retain the denominator and scale of their source evidence."""

import pytest

from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
from adaptive_document_agent.models import Observation
from adaptive_document_agent.services.financial_formatter import format_compact_currency, normalize_raw_unit
from adaptive_document_agent.services.pptx_export import (
    _appendix_display_unit, _appendix_display_value, _display_source_unit, _unit_label,
)


@pytest.mark.parametrize("raw, expected", [
    ("RMB in thousands/unit", "RMB '000/unit"),
    ("RMB in thousands / unit", "RMB '000/unit"),
    ("USD per customer", "USD/customer"),
    ("USD per hour", "USD/hour"),
    ("MWh per employee", "MWh/employee"),
    ("USD per full time equivalent employee", "USD/full time equivalent employee"),
    ("USD/kg/day", "USD/kg/day"),
    ("RMB in thousands", "RMB '000"),
])
def test_explicit_unit_denominators_survive_formatting(raw, expected):
    assert normalize_raw_unit(raw) == expected


def test_price_appendix_uses_reported_scale_and_keeps_underlying_values():
    price = Observation(id="price", metric_original="Average selling price", value=65900,
                        raw_value="65.9", raw_unit="RMB in thousands/unit", unit="currency",
                        unit_scale=1000, currency="RMB", confidence=1)
    original = price.model_dump()
    semantic = classify_metric(price.metric_original, raw_unit=price.raw_unit, unit=price.unit)
    assert _appendix_display_unit(price, semantic) == "RMB '000/unit"
    assert _appendix_display_value(price, semantic) == "65.9"
    assert _display_source_unit(price) == "RMB '000/unit"
    assert _unit_label([price], "thousands") == "RMB thousands/unit"
    assert price.model_dump() == original


def test_unknown_price_basis_is_not_guessed_from_metric_name():
    price = Observation(id="price", metric_original="Average selling price", value=65900,
                        raw_value="65.9", raw_unit="RMB in thousands", unit="currency",
                        unit_scale=1000, currency="RMB", confidence=1)
    semantic = classify_metric(price.metric_original, raw_unit=price.raw_unit, unit=price.unit)
    assert _appendix_display_unit(price, semantic) == "RMB million"
    assert "/unit" not in _unit_label([price], "thousands")


def test_compact_monetary_rate_retains_explicit_denominator():
    assert format_compact_currency(21000, raw_unit="USD/unit", is_base_value=True) == "US$ 21k/unit"
    assert format_compact_currency(21000, raw_unit="USD / unit", is_base_value=True) == "US$ 21k/unit"


@pytest.mark.parametrize(("value", "expected"), [
    (8200, "RMB 8.2k/unit"), (8100, "RMB 8.1k/unit"), (8400, "RMB 8.4k/unit"),
    (65900, "RMB 65.9k/unit"), (-61250, "-RMB 61.25k/unit"),
])
def test_unit_prices_do_not_collapse_distinct_reported_values(value, expected):
    assert format_compact_currency(value, raw_unit="RMB/unit", is_base_value=True) == expected
