"""A ratio's direction must not be attributed to its named denominator."""

from adaptive_document_agent.models import Observation, PresentationPlan, PresentationSlide, SourceEvidence
from adaptive_document_agent.services.qa_reporter import repair_presentation_plan_claims
from adaptive_document_agent.validation.claim_validator import (
    ClaimValidator, repair_presentation_plan_from_issues,
)
from tests.test_pptx_export import _result


def _observations():
    rows = (
        ("Annual research and development expenditure", "currency", (47.069, 52.091, 70.407)),
        ("Annual total operating expenditure", "currency", (137.137, 190.897, 250.861)),
        ("Annual research and development expenditure ratio %", "percent", (34.3, 27.3, 28.1)),
    )
    return [Observation(
        id=f"{row}-{year}", metric_original=row, value=value, raw_value=str(value),
        unit=unit, period=f"FY{year}", period_basis="FY", period_type="fiscal_year",
        validation_status="valid", evidence=[SourceEvidence(
            page=1, row_label=row, text=str(value), extraction_method="digital_table", confidence=.9,
        )], confidence=.9,
    ) for row, unit, values in rows for year, value in zip((2021, 2022, 2023), values)]


def test_possessive_ratio_direction_uses_reported_ratio_values():
    observations = _observations()
    correct = PresentationSlide(id="rd", slide_type="analysis", title=(
        "Annual research and development expenditure rose while its ratio to "
        "annual total operating expenditure fell."
    ))
    assert not ClaimValidator().validate_slide(correct, observations)

    wrong = correct.model_copy(update={"title": correct.title.replace("fell", "rose")})
    issues = ClaimValidator().validate_slide(wrong, observations)
    contradictions = [issue for issue in issues if issue.code == "directional_contradiction"]
    assert len(contradictions) == 1
    assert contradictions[0].metric_name == "annual research and development expenditure ratio %"
    assert contradictions[0].expected_direction == "DECREASED"

    plan = PresentationPlan(title="Ratio", slides=[wrong])
    repair_presentation_plan_from_issues(plan, issues)
    assert "expenditure declined overall, with a partial rebound in the final year" in plan.slides[0].title
    assert "expenditure rose while" in plan.slides[0].title


def test_unbound_possessive_ratio_does_not_borrow_denominator_direction():
    observations = _observations()[:6]
    slide = PresentationSlide(id="rd", slide_type="analysis", title=(
        "Annual research and development expenditure rose while its ratio to "
        "annual total operating expenditure fell."
    ))
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(issue.code == "direction_ratio_subject_ambiguous" for issue in issues)
    assert not any(issue.code == "directional_contradiction" and
                   issue.metric_name == "annual total operating expenditure" for issue in issues)


def test_possessive_share_of_denominator_uses_reported_ratio_values():
    observations = _observations()
    title = (
        "Annual research and development expenditure increased FY2021–FY2023 "
        "while its share of annual total operating expenditure declined."
    )
    slide = PresentationSlide(id="rd", slide_type="analysis", title=title)
    assert not ClaimValidator().validate_slide(slide, observations)

    slide.title = title.replace("declined", "increased")
    issues = ClaimValidator().validate_slide(slide, observations)
    contradictions = [issue for issue in issues if issue.code == "directional_contradiction"]
    assert len(contradictions) == 1
    assert contradictions[0].metric_name == "annual research and development expenditure ratio %"
    assert contradictions[0].expected_direction == "DECREASED"


def test_unbound_possessive_share_does_not_borrow_denominator_direction():
    observations = _observations()[:6]
    slide = PresentationSlide(id="rd", slide_type="analysis", title=(
        "Annual research and development expenditure increased FY2021–FY2023 "
        "while its share of annual total operating expenditure declined."
    ))
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(issue.code == "direction_ratio_subject_ambiguous" for issue in issues)
    assert not any(issue.code == "directional_contradiction" and
                   issue.metric_name == "annual total operating expenditure" for issue in issues)


def test_qa_repair_records_the_corrected_direction_in_export_audit():
    result = _result()
    result.observations = _observations()
    result.charts = []
    result.insights = []
    result.presentation_plan = PresentationPlan(title="Ratio", editorial_notes=["Earlier repair"], slides=[
        PresentationSlide(id="rd", slide_type="analysis", title=(
            "Annual research and development expenditure rose while its ratio to "
            "annual total operating expenditure rose."
        ), observation_ids=[item.id for item in result.observations]),
    ])
    repairs = repair_presentation_plan_claims(result)
    assert len(repairs) == 1
    assert result.presentation_plan.editorial_notes == ["Earlier repair", repairs[0]]
    snapshot = result.presentation_plan.model_dump()
    assert repair_presentation_plan_claims(result) == []
    assert result.presentation_plan.model_dump() == snapshot


def test_nonfinancial_ratio_uses_the_same_unique_source_label_binding():
    rows = (
        ("Service utilisation", "count", (40, 50)),
        ("Scheduled capacity", "count", (100, 200)),
        ("Service utilisation ratio", "percent", (40, 25)),
    )
    observations = [Observation(
        id=f"{row}-{year}", metric_original=row, value=value, raw_value=str(value),
        unit=unit, period=f"FY{year}", period_basis="FY", period_type="fiscal_year",
        validation_status="valid", evidence=[SourceEvidence(
            page=3, row_label=row, text=str(value), extraction_method="digital_table", confidence=.9,
        )], confidence=.9,
    ) for row, unit, values in rows for year, value in zip((2022, 2023), values)]
    title = "Service utilisation rose while its ratio to scheduled capacity fell."
    slide = PresentationSlide(id="utilisation", slide_type="analysis", title=title)
    assert not ClaimValidator().validate_slide(slide, observations)

    slide.title = title.replace("fell", "rose")
    issues = ClaimValidator().validate_slide(slide, observations)
    contradictions = [issue for issue in issues if issue.code == "directional_contradiction"]
    assert len(contradictions) == 1
    assert contradictions[0].metric_name == "service utilisation ratio"
    assert contradictions[0].expected_direction == "DECREASED"


def test_source_derived_initialism_binds_ratio_without_issuer_aliases():
    observations = _observations()
    slide = PresentationSlide(id="rd", slide_type="analysis", title=(
        "Annual R&D expenditure rose while its ratio to annual total operating expenditure declined."
    ))
    assert not ClaimValidator().validate_slide(slide, observations)

    other = [item.model_copy(update={
        "id": item.id.replace("Annual research and development", "Annual alpha and beta"),
        "metric_original": item.metric_original.replace(
            "Annual research and development", "Annual alpha and beta"
        ),
    }) for item in observations]
    other_slide = PresentationSlide(id="utilisation", slide_type="analysis", title=(
        "Annual A&B expenditure rose while its ratio to annual total operating expenditure declined."
    ))
    assert not ClaimValidator().validate_slide(other_slide, other)


def test_omitted_annual_qualifier_binds_initialism_and_its_share():
    observations = _observations()
    slide = PresentationSlide(id="rd", slide_type="analysis", title=(
        "R&D expenditure rose between FY2021 and FY2023 while its share of "
        "total operating expenditure declined."
    ))
    assert not ClaimValidator().validate_slide(slide, observations)
    for word, metric in (("rose", "annual research and development expenditure"),
                         ("declined", "annual research and development expenditure ratio %")):
        wrong = slide.model_copy(update={"title": slide.title.replace(word, "fell" if word == "rose" else "rose")})
        contradictions = [issue for issue in ClaimValidator().validate_slide(wrong, observations)
                          if issue.code == "directional_contradiction"]
        assert len(contradictions) == 1
        assert contradictions[0].metric_name == metric


def test_omitted_annual_qualifier_does_not_resolve_duplicate_ratio_subjects():
    observations = _observations()
    observations += [item.model_copy(update={"id": item.id + "-other", "metric_original":
                     "Research and development expenditure ratio to another base"})
                     for item in observations[-3:]]
    slide = PresentationSlide(id="rd", slide_type="analysis", title=(
        "R&D expenditure rose between FY2021 and FY2023 while its share declined."
    ))
    assert any(issue.code == "direction_ratio_subject_ambiguous"
               for issue in ClaimValidator().validate_slide(slide, observations))
