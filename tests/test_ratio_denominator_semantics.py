"""Expense labels cannot invent a denominator or retain one from a legacy export."""

import pytest

from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric,
    sanitize_metric_label,
)
from adaptive_document_agent.models import Observation, SourceEvidence
from adaptive_document_agent.services.financial_formatter import shorten_metric_title
from adaptive_document_agent.services.financial_normalizer import FinancialNormalizer
from adaptive_document_agent.services.language_qa import clean_metric_label


@pytest.mark.parametrize("name", [
    "Annual research and development expenditure ratio %",
    "Research and development expenses ratio",
    "R&D ratio",
    "Selling and marketing expenses ratio",
    "Selling and distribution expenses ratio",
    "Administrative expenses ratio",
    "SG&A ratio",
    "Cost of sales ratio",
    "Research and development expenses / annual total operating expenditure",
    "Research and development expenses as % of net revenue",
    "Research and development expenses ratio of total operating expenditure",
    "Research and development expenses ratio; administrative expenses share of revenue",
])
def test_expense_ratio_keeps_unknown_or_different_denominator(name):
    assert sanitize_metric_label(name) == name
    assert clean_metric_label(name) == name
    assert shorten_metric_title(name) == name


@pytest.mark.parametrize("name", [
    "Research and development expenses: %of Revenue",
    "Research and development expenses: share of revenue",
    "Research and development expenses (as % of revenue)",
    "Research and development expenditure ratio to revenue",
    "R&D / Revenue",
])
def test_explicit_revenue_ratio_still_shortens(name):
    assert sanitize_metric_label(name) == "R&D / revenue"
    assert clean_metric_label(name) == "R&D / Revenue"
    assert shorten_metric_title(name) == "R&D / Revenue"


def test_annual_research_ratio_remains_percentage_without_inventing_denominator():
    name = "Annual research and development expenditure ratio %"
    semantics = classify_metric(name, value=31.7, raw_unit="%", unit="percent")
    assert semantics.clean_name == name
    assert semantics.short_display_name == name
    assert semantics.unit_family == "percentage"
    assert semantics.is_expense_ratio


def _ratio_observation(**overrides):
    fields = dict(
        id="annual-research-ratio",
        metric_original="Annual research and development expenditure ratio %",
        metric_canonical="Annual research and development expenditure ratio %",
        value=31.7,
        raw_value="31.7%",
        raw_unit="%",
        unit="percent",
        unit_family="percentage",
        semantic_type="ratio_share",
        unit_scale=1.0,
        period="FY2024",
        presentation_label="R&D / revenue",
        display_value="31.7",
        display_unit="%",
        evidence=[SourceEvidence(
            page=17,
            text="31.7%",
            table_id="research-spending",
            row_label="Annual research and development expenditure ratio",
            column_label="FY2024",
            extraction_method="digital_table",
            confidence=0.9,
        )],
        confidence=0.9,
    )
    fields.update(overrides)
    return Observation(**fields)


@pytest.mark.parametrize("canonical,presentation", [
    ("Annual research and development expenditure ratio %", "R&D / revenue"),
    ("R&D / revenue", "R&D / revenue"),
    ("R&D / revenue", ""),
])
def test_legacy_or_canonical_revenue_invention_repaired_only_in_display(canonical, presentation):
    obs = _ratio_observation(metric_canonical=canonical, presentation_label=presentation)
    source_before = obs.model_dump(include={
        "metric_original", "metric_canonical", "value", "raw_value", "raw_unit",
        "unit_scale", "period", "evidence",
    })
    FinancialNormalizer.normalize_observation(obs)
    assert obs.presentation_label == obs.metric_original
    assert obs.model_dump(include=set(source_before)) == source_before
    first_result = obs.model_dump()
    FinancialNormalizer.normalize_observation(obs)
    assert obs.model_dump() == first_result


@pytest.mark.parametrize("family,label", [
    ("Selling and distribution expenses ratio", "Selling & Distribution / Revenue"),
    ("Administrative expenses ratio", "Admin / Revenue"),
    ("Cost of sales ratio", "Cost of Sales / Revenue"),
    ("SG&A ratio", "SG&A / Revenue"),
])
def test_legacy_repair_applies_to_expense_families(family, label):
    obs = _ratio_observation(metric_original=family, metric_canonical=family, presentation_label=label)
    FinancialNormalizer.normalize_observation(obs)
    assert obs.presentation_label == family


def test_matching_source_column_can_support_revenue_denominator():
    obs = _ratio_observation(metric_original="Research and development expenses")
    obs.evidence[0].row_label = "Research and development expenses"
    obs.evidence[0].column_label = "%of Revenue"
    FinancialNormalizer.normalize_observation(obs)
    assert obs.presentation_label == "R&D / revenue"


def test_other_rows_revenue_denominator_cannot_support_research_ratio():
    obs = _ratio_observation()
    obs.evidence[0].row_label = "Administrative expenses"
    obs.evidence[0].column_label = "% of Revenue"
    obs.evidence[0].text = "Research spending ratio 31.7%; administrative expenses / revenue 14.0%"
    FinancialNormalizer.normalize_observation(obs)
    assert obs.presentation_label == obs.metric_original


def test_explicit_source_denominator_wins_over_conflicting_header():
    name = "Research and development expenses ratio of annual total operating expenditure"
    obs = _ratio_observation(metric_original=name)
    obs.evidence[0].row_label = "Research and development expenses"
    obs.evidence[0].column_label = "%of Revenue"
    FinancialNormalizer.normalize_observation(obs)
    assert obs.presentation_label == name


@pytest.mark.parametrize("label", [
    "R&D / total operating expenditure",
    "R&D / net revenue",
    "Annual R&D expenditure ratio",
])
def test_existing_nonlegacy_display_label_is_preserved(label):
    obs = _ratio_observation(presentation_label=label)
    FinancialNormalizer.normalize_observation(obs)
    assert obs.presentation_label == label


def test_correct_signed_revenue_ratio_keeps_source_and_display_semantics():
    obs = _ratio_observation(
        metric_original="Research and development expenses: %of Revenue",
        metric_canonical="Research and development expenses: %of Revenue",
        value=-23.6,
        raw_value="(23.6)",
        presentation_label="R&D / revenue",
    )
    FinancialNormalizer.normalize_observation(obs)
    assert obs.presentation_label == "R&D / revenue"
    assert obs.value == -23.6
    assert obs.raw_value == "(23.6)"
