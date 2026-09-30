"""Endpoint amounts belong to the source-defined qualified measure."""

import pytest

from adaptive_document_agent.models import PresentationSlide
from adaptive_document_agent.validation.scoped_narrative_values import scoped_value_errors
from tests.test_p0_composition import observation
from tests.test_possessive_ratio_direction import _observations


@pytest.mark.parametrize("component", ["title", "message", "bullets"])
def test_source_margin_alias_prevents_nested_profit_from_owning_percentages(component):
    observations = [observation("profit", "Gross profit", 88080000),
                    observation("margin1", "Gross profit: %of Revenue", 50.5, unit="percent"),
                    observation("margin2", "Gross profit: %of Revenue", 43.5, unit="percent")]
    text = "Gross profit rose while gross profit margin fell from 50.5% to 43.5%."
    slide = PresentationSlide(id="s", slide_type="analysis", title="Comparison")
    setattr(slide, component, [text] if component == "bullets" else text)
    assert not scoped_value_errors(slide, observations)
    setattr(slide, component, ["Gross profit rose to 43.5."] if component == "bullets" else "Gross profit rose to 43.5.")
    assert scoped_value_errors(slide, observations)


@pytest.mark.parametrize("term", ["ratio to", "share of"])
def test_possessive_ratio_endpoints_cannot_be_attributed_to_denominator(term):
    observations = _observations()
    text = (f"R&D expenditure rose between FY2021 and FY2023 while its {term} "
            "annual total operating expenditure fell from 34.3% to 28.1%.")
    slide = PresentationSlide(id="s", slide_type="analysis", title=text)
    assert not scoped_value_errors(slide, observations)
    slide.title = text.replace("34.3%", "137.137")
    assert scoped_value_errors(slide, observations)


def test_unbound_ratio_pronoun_does_not_lend_denominator_amounts_to_the_ratio():
    observations = _observations()[:6]
    slide = PresentationSlide(id="s", slide_type="analysis", title=(
        "R&D expenditure rose while its ratio to annual total operating expenditure fell from 137.137 to 250.861."
    ))
    assert scoped_value_errors(slide, observations)


def test_category_qualifier_belongs_to_its_measure_not_a_second_source_row():
    asp = [observation(f"asp{i}", "ASP", value, unit="currency") for i, value in enumerate((65900, 56600))]
    for item in asp:
        item.category_dimensions = {"category": "Six-axis cobots"}
    composition = observation("mix", "Six-axis cobots", 46.8, unit="percent")
    other = observation("four", "ASP", 8400, unit="currency")
    other.category_dimensions = {"category": "Four-axis cobots"}
    slide = PresentationSlide(id="s", slide_type="analysis", title=(
        "ASP for six-axis cobots declined from RMB65,900 to RMB56,600."
    ))
    observations = [*asp, composition, other]
    assert not scoped_value_errors(slide, observations)
    slide.title = slide.title.replace("56,600", "8,400")
    assert scoped_value_errors(slide, observations)


def test_parenthesized_source_alternative_does_not_fall_back_to_cash_balance():
    observations = [observation("flow", "Net cash from/(used in) operating activities", 6367000),
                    observation("balance", "Cash and cash equivalents", 149093000)]
    slide = PresentationSlide(id="s", slide_type="analysis", title=(
        "Net cash from operating activities decreased from RMB6.367 million."
    ))
    assert not scoped_value_errors(slide, observations)
    slide.title = "Net cash from operating activities decreased from RMB149.093 million."
    assert scoped_value_errors(slide, observations)


@pytest.mark.parametrize("source,claim", [("65900.0", "RMB65,900"), ("56600.00", "56,600"),
                                        ("-1250.000", "-1,250"), ("34.300%", "34.3%")])
def test_exact_integer_and_decimal_spellings_share_numeric_identity(source, claim):
    from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator as V
    assert V._numbers(source) == V._numbers(claim)
    assert V._numbers("56600.01") != V._numbers("56600")
    assert V._numbers("34.3%") != V._numbers("34.3")
