"""Every source category in an elided joint subject owns the predicate."""

import pytest

from adaptive_document_agent.validation.claim_validator import ClaimValidator
from tests.test_segmented_direction_claims import _series, _slide


def _observations():
    return [item for label, values in (
        ("Six-axis cobots", [44.1, 37.0, 47.2]),
        ("Integrated cobots", [33.1, 51.8, 53.1]),
        ("Four-axis cobots", [60.8, 50.4, 54.8]),
    ) for item in _series(f"{label}: Gross profit margin", values, years=(2021, 2022, 2023))]


@pytest.mark.parametrize("component", ["title", "message", "bullets"])
def test_shared_margin_predicate_binds_each_named_source_category(component):
    observations = _observations()
    text = ("Six-axis and integrated cobot gross margins rose while four-axis gross margin fell "
            "between FY2021 and FY2023.")
    assert not ClaimValidator().validate_slide(_slide(text, observations, component), observations)


@pytest.mark.parametrize("wrong_category", ["Six-axis", "Integrated"])
def test_shared_predicate_checks_both_categories_independently(wrong_category):
    observations = _observations()
    for item in observations:
        if item.metric_original.startswith(wrong_category) and item.period == "FY2023":
            item.value = 20
            item.raw_value = "20"
    text = ("Six-axis and integrated cobot gross margins rose while four-axis gross margin fell "
            "between FY2021 and FY2023.")
    issues = ClaimValidator().validate_slide(_slide(text, observations), observations)
    contradictions = [issue for issue in issues if issue.code == "directional_contradiction"]
    assert len(contradictions) == 1
    assert contradictions[0].metric_name.startswith(wrong_category.casefold())
    assert contradictions[0].start_period == "FY2021"
    assert contradictions[0].end_period == "FY2023"


@pytest.mark.parametrize("subject", ["Six-axis and unknown cobot", "Six-axis and six-axis cobot"])
def test_unknown_or_duplicate_conjunct_cannot_borrow_one_valid_owner(subject):
    observations = _observations()
    text = f"{subject} gross margins rose between FY2021 and FY2023."
    issues = ClaimValidator().validate_slide(_slide(text, observations), observations)
    assert any(issue.code == "direction_scope_ambiguous" for issue in issues)


def test_shared_predicate_does_not_infer_a_start_from_one_endpoint():
    observations = _observations()
    issues = ClaimValidator().validate_slide(
        _slide("Six-axis and integrated cobot gross margins rose in FY2023.", observations), observations,
    )
    assert sum(issue.code == "direction_scope_ambiguous" for issue in issues) == 2


def test_source_category_binding_is_not_specific_to_one_product():
    observations = [item for label, values in (
        ("Northern devices", [40, 50]), ("Southern devices", [30, 45]), ("Western devices", [50, 40]),
    ) for item in _series(f"{label}: Gross profit margin", values, years=(2022, 2023))]
    text = ("Northern and southern device gross margins rose while western gross margin fell "
            "between FY2022 and FY2023.")
    assert not ClaimValidator().validate_slide(_slide(text, observations), observations)
