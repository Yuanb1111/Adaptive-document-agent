"""Directional repairs must use the period segment described by each predicate."""

from __future__ import annotations

import pytest

from adaptive_document_agent.models import Observation, PresentationPlan, PresentationSlide, SourceEvidence
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan


def _series(metric: str, values: list[float], *, years: tuple[int, ...] | None = None) -> list[Observation]:
    years = years or tuple(range(2023, 2023 + len(values)))
    canonical = metric.casefold().replace(" ", "_")
    return [
        Observation(
            id=f"{canonical}_{year}",
            metric_original=metric,
            metric_canonical=canonical,
            value=value,
            raw_value=f"({abs(value):,.0f})" if value < 0 else f"{value:,.0f}",
            unit="currency",
            raw_unit="CNY million",
            currency="CNY",
            period=f"FY{year}",
            period_type="fiscal_year",
            confidence=0.95,
            evidence=[SourceEvidence(page=8, text=f"{year}: {value}", extraction_method="digital_table", confidence=0.95)],
        )
        for year, value in zip(years, values, strict=True)
    ]


def _slide(text: str, observations: list[Observation], component: str = "message") -> PresentationSlide:
    kwargs = {"title": "Reported movements", component: [text] if component == "bullets" else text}
    return PresentationSlide(
        id="movement",
        slide_type="analysis",
        observation_ids=[o.id for o in observations],
        source_pages=[8],
        **kwargs,
    )


def _component(slide: PresentationSlide, component: str) -> str:
    return slide.bullets[0] if component == "bullets" else getattr(slide, component)


@pytest.mark.parametrize("component", ["title", "message", "bullets"])
@pytest.mark.parametrize("text", [
    "Net loss widened then narrowed.",
    "Net loss widened and then narrowed.",
    "Net loss widened before narrowing.",
])
def test_supported_loss_reversal_is_preserved(text: str, component: str) -> None:
    observations = _series("Net loss", [-100, -160, -125])
    slide = _slide(text, observations, component)
    before = [o.model_dump() for o in observations]
    assert not ClaimValidator().validate_slide(slide, observations)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert _component(repaired.slides[0], component) == text
    assert not repairs
    assert [o.model_dump() for o in observations] == before


@pytest.mark.parametrize(("text", "expected"), [
    ("Net loss widened then widened.", "Net loss widened then narrowed."),
    ("Net loss narrowed then widened.", "Net loss widened then narrowed."),
    ("Net loss widened and then widened.", "Net loss widened and then narrowed."),
    ("Net loss widened before widening.", "Net loss widened before narrowing."),
])
def test_each_loss_predicate_is_repaired_once_against_its_own_segment(text: str, expected: str) -> None:
    observations = _series("Net loss", [-100, -160, -125])
    slide = _slide(text, observations)
    before_observations = [o.model_dump() for o in observations]
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(i.code == "directional_contradiction" for i in issues)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == expected
    assert repairs
    assert not ClaimValidator().validate_slide(repaired.slides[0], observations)
    first_repair = repaired.model_dump()
    repaired, second_repairs = repair_presentation_plan(repaired, observations)
    assert repaired.model_dump() == first_repair
    assert not second_repairs
    assert [o.model_dump() for o in observations] == before_observations


def test_repeated_direction_issue_identifies_only_the_later_token_and_periods() -> None:
    observations = _series("Net loss", [-100, -160, -125])
    text = "Net loss widened then widened."
    issues = ClaimValidator().validate_slide(_slide(text, observations), observations)
    contradictions = [i for i in issues if i.code == "directional_contradiction"]
    assert len(contradictions) == 1
    issue = contradictions[0]
    assert issue.expected_direction == "LOSS_NARROWED"
    assert issue.start_period == "FY2024"
    assert issue.end_period == "FY2025"
    assert set(issue.related_ids) == {observations[1].id, observations[2].id}
    assert issue.claim_start == text.rindex("widened")
    assert text[issue.claim_start:issue.claim_end] == "widened"


@pytest.mark.parametrize(("metric", "values", "text", "expected"), [
    ("Revenue", [100, 160, 125], "Revenue rose then fell.", "Revenue rose then fell."),
    ("Revenue", [100, 160, 125], "Revenue increased then increased.", "Revenue increased then decreased."),
    ("Operating expenses", [-100, -160, -125], "Operating expenses increased then decreased.", "Operating expenses increased then decreased."),
    ("Operating expenses", [-100, -160, -125], "Operating expenses increased then increased.", "Operating expenses increased then decreased."),
])
def test_segment_validation_respects_generic_metric_and_signed_expense_semantics(
    metric: str, values: list[float], text: str, expected: str,
) -> None:
    observations = _series(metric, values)
    plan = PresentationPlan(title="Reported movements", slides=[_slide(text, observations)])
    repaired, _ = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == expected
    assert not ClaimValidator().validate_slide(repaired.slides[0], observations)


@pytest.mark.parametrize("separator", ["; ", " and "])
def test_independent_metric_tail_keeps_its_own_predicate(separator: str) -> None:
    observations = _series("Net loss", [-100, -160, -125]) + _series("Finance costs", [-3, -4, -6])
    tail = "finance costs increased."
    text = "Net loss widened then widened" + separator + tail
    plan = PresentationPlan(title="Reported movements", slides=[_slide(text, observations)])
    repaired, _ = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == "Net loss widened then narrowed" + separator + tail
    assert not ClaimValidator().validate_slide(repaired.slides[0], observations)


@pytest.mark.parametrize(("text", "expected"), [
    ("Net loss narrowed from FY2024 to FY2025.", "Net loss narrowed from FY2024 to FY2025."),
    ("Net loss widened from FY2024 to FY2025.", "Net loss narrowed from FY2024 to FY2025."),
    ("Net loss widened from FY2023 to FY2024 then widened from FY2024 to FY2025.",
     "Net loss widened from FY2023 to FY2024 then narrowed from FY2024 to FY2025."),
])
def test_explicit_periods_select_an_interior_interval(text: str, expected: str) -> None:
    observations = _series("Net loss", [-100, -160, -125, -200])
    plan = PresentationPlan(title="Reported movements", slides=[_slide(text, observations)])
    repaired, _ = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == expected
    assert not ClaimValidator().validate_slide(repaired.slides[0], observations)


@pytest.mark.parametrize(("values", "text"), [
    ([-100, -160, -125, -180], "Net loss widened then narrowed."),
    ([-100, -160, -125], "Net loss widened from FY2022 to FY2024."),
    ([-100, -160, -125], "Net loss widened from FY2023 to FY2024 then widened from FY2024 to FY2026."),
])
def test_unresolved_or_missing_period_scope_is_not_guessed(values: list[float], text: str) -> None:
    observations = _series("Net loss", values)
    slide = _slide(text, observations)
    before_observations = [o.model_dump() for o in observations]
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(i.code == "direction_scope_ambiguous" and i.severity == "error" for i in issues)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs
    assert [o.model_dump() for o in observations] == before_observations


def test_question_range_repairs_matching_title_and_summary_endpoint() -> None:
    observations = _series("Gross profit margin", [31.3, 28.3, 29.5], years=(2021, 2022, 2023))
    for item in observations:
        item.unit = "percent"
        item.raw_unit = "%"
    title = "Raw materials dominated cost of sales while gross margin narrowed by FY2023."
    ids = [item.id for item in observations]
    summary = PresentationSlide(
        id="summary", slide_type="executive_summary", title="Executive Summary",
        bullets=[title], bullet_observation_ids=[ids], observation_ids=ids,
    )
    analysis = PresentationSlide(
        id="margin", slide_type="analysis", title=title,
        message="How did gross margin move across FY2021 to FY2023?",
        observation_ids=ids,
    )
    plan = PresentationPlan(title="Reported movements", slides=[summary, analysis])
    assert {issue.code for issue in ClaimValidator().validate_plan(plan, observations)} == {
        "direction_scope_ambiguous"
    }
    before = [item.model_dump() for item in observations]
    repaired, repairs = repair_presentation_plan(plan, observations)
    expected = "Raw materials dominated cost of sales while gross margin narrowed from FY2021 to FY2023."
    assert repaired.slides[0].bullets == [expected]
    assert repaired.slides[1].title == expected
    assert repairs
    assert not ClaimValidator().validate_plan(repaired, observations)
    assert [item.model_dump() for item in observations] == before
    assert not repair_presentation_plan(repaired, observations)[1]


def test_question_range_does_not_rescue_unsupported_endpoint_claim() -> None:
    observations = _series("Gross profit margin", [31.3, 28.3, 29.5], years=(2021, 2022, 2023))
    text = "Gross margin increased by FY2023."
    slide = _slide(text, observations, "title")
    slide.message = "How did gross margin move across FY2021 to FY2023?"
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].title == text
    assert not repairs
    assert any(issue.code == "direction_scope_ambiguous"
               for issue in ClaimValidator().validate_plan(repaired, observations))


def test_question_range_repairs_only_ambiguous_sign_crossing_in_two_metric_title() -> None:
    cash_flow = _series("Operating cash flow", [6, -116, -157], years=(2021, 2022, 2023))
    cash_balance = _series("Cash at period end", [149, 297, 110], years=(2021, 2022, 2023))
    observations = cash_flow + cash_balance
    title = ("Operating cash flow turned negative in FY2023, and cash at period end "
             "fell from FY2021 to FY2023.")
    question = "How did operating cash flow and cash at period end evolve from FY2021 to FY2023?"
    ids = [item.id for item in observations]
    summary = PresentationSlide(
        id="summary", slide_type="executive_summary", title="Executive Summary",
        bullets=[title], bullet_observation_ids=[ids], observation_ids=ids,
    )
    analysis = PresentationSlide(
        id="cash", slide_type="analysis", title=title, message=question,
        observation_ids=ids,
    )
    plan = PresentationPlan(title="Reported movements", slides=[summary, analysis])
    assert {issue.code for issue in ClaimValidator().validate_plan(plan, observations)} == {
        "direction_scope_ambiguous"
    }
    before = [item.model_dump() for item in observations]
    repaired, repairs = repair_presentation_plan(plan, observations)
    expected = ("Operating cash flow turned negative between FY2021 and FY2023, "
                "and cash at period end fell from FY2021 to FY2023.")
    assert repaired.slides[0].bullets == [expected]
    assert repaired.slides[1].title == expected
    assert repairs
    assert not ClaimValidator().validate_plan(repaired, observations)
    assert [item.model_dump() for item in observations] == before
    assert not repair_presentation_plan(repaired, observations)[1]


@pytest.mark.parametrize("values,question", [
    ([-6, -116, -157], "How did operating cash flow evolve from FY2021 to FY2023?"),
    ([6, -116, -157], "How did operating cash flow evolve from FY2021 to FY2022?"),
])
def test_question_range_does_not_rescue_unsupported_sign_crossing(
    values: list[float], question: str,
) -> None:
    observations = _series("Operating cash flow", values, years=(2021, 2022, 2023))
    title = "Operating cash flow turned negative in FY2023."
    slide = _slide(title, observations, "title")
    slide.message = question
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].title == title
    assert not repairs
    assert any(issue.code == "direction_scope_ambiguous"
               for issue in ClaimValidator().validate_plan(repaired, observations))


def test_category_qualified_margin_claims_keep_three_source_series_separate() -> None:
    rows = (
        ("Algorithm modules", [37.4, 31.3, 26.0]),
        ("Sensors", [18.5, 15.2, 20.4]),
        ("Robot lawn mowers", [49.2, 33.6, 42.3]),
    )
    observations = []
    for category, values in rows:
        for item in _series("Gross profit margin", values, years=(2023, 2024, 2025)):
            item.id = f"{category}_{item.period}"
            item.unit = "percent"
            item.raw_unit = "%"
            item.category_dimensions = {"category": category}
            observations.append(item)
    text = ("Algorithm module gross margin declined from FY2023 to FY2025, "
            "sensor gross margin rose, and robot lawn mower gross margin declined.")
    assert not ClaimValidator().validate_slide(_slide(text, observations, "bullets"), observations)
    unqualified = "Gross margin declined from FY2023 to FY2025."
    issues = ClaimValidator().validate_slide(_slide(unqualified, observations), observations)
    assert any(issue.code == "direction_scope_ambiguous" for issue in issues)


def test_shared_margin_alias_binds_to_qualified_source_metric() -> None:
    warehouse = _series("Gross margin for warehouse fulfillment solutions %",
                        [36.6, 39.0, 39.2], years=(2022, 2023, 2024))
    industrial = _series("Gross margin for industrial material transport solutions %",
                         [18.4, 12.9, 12.1], years=(2022, 2023, 2024))
    observations = [*warehouse, *industrial]
    for item in observations:
        item.unit, item.raw_unit, item.currency = "percent", "%", None
    text = ("Warehouse fulfillment gross margin rose while industrial material "
            "transport gross margin fell from FY2022 to FY2024.")
    slide = _slide(text, observations, "bullets")
    assert not ClaimValidator().validate_slide(slide, observations)
    repaired, repairs = repair_presentation_plan(PresentationPlan(title="Margins", slides=[slide]),
                                                 observations)
    assert repaired.slides[0].bullets == [text]
    assert not repairs
    slide.bullets = [text.replace("transport gross margin fell", "transport gross margin rose")]
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any("industrial_material_transport" in issue.metric_name
               and issue.offending_direction == "rose" for issue in issues)
    slide.bullets = ["Gross margin rose from FY2022 to FY2024."]
    assert any(issue.code == "direction_scope_ambiguous"
               for issue in ClaimValidator().validate_slide(slide, observations))


def test_financing_cash_flow_does_not_borrow_cash_balance_direction() -> None:
    financing = _series("Net cash generated from/(used in) financing activities",
                        [1505, 150, -56], years=(2022, 2023, 2024))
    balance = _series("Cash and cash equivalents at the end of the year",
                      [1121, 760, 636], years=(2022, 2023, 2024))
    text = ("Financing cash flow turned negative and ending cash decreased "
            "from FY2022 to FY2024.")
    observations = [*financing, *balance]
    slide = _slide(text, observations, "bullets")
    assert not ClaimValidator().validate_slide(slide, observations)
    repaired, repairs = repair_presentation_plan(PresentationPlan(title="Cash", slides=[slide]),
                                                 observations)
    assert repaired.slides[0].bullets == [text]
    assert not repairs


def test_unique_cash_balance_runs_bind_their_stated_end_dates() -> None:
    observations = _series("Cash and cash equivalents", [27, 46, 119, 110],
                           years=(2023, 2024, 2025, 2026))
    for item, period in zip(observations,
                            ("2023-12-31", "2024-12-31", "2025-12-31", "2026-02-28")):
        item.period = period
        item.period_type = "balance_sheet_date"
    title = "Cash and cash equivalents grew then eased."
    bullet = ("Cash and cash equivalents grew through 2025-12-31 "
              "before easing at 2026-02-28.")
    slide = PresentationSlide(id="cash", slide_type="analysis", title=title,
                              bullets=[bullet], observation_ids=[o.id for o in observations])
    assert not ClaimValidator().validate_slide(slide, observations)
    slide.bullets = [bullet.replace("2025-12-31", "2024-12-31")]
    assert any(issue.code == "direction_scope_ambiguous"
               for issue in ClaimValidator().validate_slide(slide, observations))


def test_accounting_before_items_is_not_a_temporal_connector() -> None:
    observations = _series("Adjusted net loss", [-55, -44, -26])
    text = ("The narrowing adjusted net loss indicates improving underlying "
            "profitability before non-recurring items.")
    assert not ClaimValidator().validate_slide(_slide(text, observations), observations)
    observations[-1].value = -70
    temporal = "Adjusted net loss narrowed before widening."
    assert not ClaimValidator().validate_slide(_slide(temporal, observations), observations)


@pytest.mark.parametrize(("text", "supported"), [
    ("Net current assets rose from year-end 2023 to 2025.", True),
    ("Net current assets rose from end of the year 2023 to 2025.", True),
    ("Net current assets rose from 2023 to 2025.", False),
    ("Net current assets rose from year-end 2023 to FY2025.", False),
    ("Net current assets rose from year-end 2025 to 2023.", False),
])
def test_explicit_year_end_range_binds_only_matching_balance_sheet_dates(
    text: str, supported: bool,
) -> None:
    observations = _series("Net current assets", [262, 241, 311], years=(2023, 2024, 2025))
    for item in observations:
        item.period = f"{item.period[-4:]}-12-31"
        item.period_type = "balance_sheet_date"
    issues = ClaimValidator().validate_slide(_slide(text, observations), observations)
    if supported:
        assert not issues
    else:
        assert any(issue.code == "direction_scope_ambiguous" for issue in issues)


def test_year_end_wording_does_not_turn_interim_dates_into_annual_dates() -> None:
    observations = _series("Net current assets", [262, 241, 311], years=(2023, 2024, 2025))
    for item in observations:
        item.period = f"{item.period[-4:]}-06-30"
        item.period_type = "balance_sheet_date"
    issues = ClaimValidator().validate_slide(
        _slide("Net current assets rose from year-end 2023 to 2025.", observations), observations,
    )
    assert any(issue.code == "direction_scope_ambiguous" for issue in issues)


def test_preposed_period_range_belongs_to_its_independent_metric() -> None:
    observations = _series("Revenue", [100, 200, 150]) + _series("Net loss", [-100, -160, -125])
    text = "Revenue increased and from FY2024 to FY2025 net loss narrowed."
    plan = PresentationPlan(title="Reported movements", slides=[_slide(text, observations)])
    repaired, repairs = repair_presentation_plan(plan, observations)
    # Revenue's overall increase and net loss's explicitly scoped narrowing
    # must never borrow one another's comparison periods.
    assert repaired.slides[0].message == text
    assert not repairs
    issues = ClaimValidator().validate_slide(repaired.slides[0], observations)
    assert all(i.code == "direction_scope_ambiguous" for i in issues)


def test_single_year_qualifier_cannot_be_validated_using_whole_series_endpoints() -> None:
    observations = _series("Net loss", [-100, -160, -125])
    text = "Net loss widened in FY2025."
    slide = _slide(text, observations)
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(i.code == "direction_scope_ambiguous" for i in issues)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


def test_longer_series_uses_the_unique_turning_point() -> None:
    observations = _series("Net loss", [-100, -120, -160, -125])
    plan = PresentationPlan(title="Reported movements", slides=[
        _slide("Net loss widened then widened.", observations),
    ])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == "Net loss widened then narrowed."
    assert len(repairs) == 1
    assert not ClaimValidator().validate_plan(repaired, observations)


def test_longer_monotonic_series_does_not_invent_a_pivot() -> None:
    observations = _series("Net loss", [-100, -120, -160, -200])
    text = "Net loss widened then narrowed."
    slide = _slide(text, observations)
    assert any(i.code == "direction_scope_ambiguous"
               for i in ClaimValidator().validate_slide(slide, observations))
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


def test_unqualified_temporal_sequence_does_not_select_between_annual_and_interim_series() -> None:
    annual = _series("Net loss", [-100, -160, -125])
    interim = _series("Net loss", [-40, -80, -60])
    for observation in interim:
        observation.id = "interim_" + observation.id
        observation.period = observation.period.replace("FY", "6M")
        observation.period_type = "interim_flow"
    observations = annual + interim
    text = "Net loss widened then narrowed."
    slide = _slide(text, observations)
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(i.code == "direction_scope_ambiguous" for i in issues)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


def test_before_inside_metric_name_is_not_a_temporal_connector() -> None:
    observations = _series("Profit before tax", [100, 150, 180])
    text = "Profit before tax increased."
    slide = _slide(text, observations)
    assert not ClaimValidator().validate_slide(slide, observations)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


def test_before_inside_next_metric_does_not_capture_its_prefix_period_range() -> None:
    observations = _series("Revenue", [100, 200, 150]) + _series("Profit before tax", [100, 200, 150])
    text = "Revenue increased and from FY2024 to FY2025 profit before tax decreased."
    slide = _slide(text, observations)
    assert not ClaimValidator().validate_slide(slide, observations)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs


def test_unqualified_temporal_group_cannot_borrow_another_metrics_annual_periods() -> None:
    annual = _series("Revenue", [100, 200, 150])
    interim = _series("Revenue", [100, 80, 120])
    for observation in interim:
        observation.id = "interim_" + observation.id
        observation.period = observation.period.replace("FY", "6M")
        observation.period_type = "interim_flow"
    observations = annual + interim + _series("Net loss", [-100, -160, -125])
    text = "Revenue decreased then increased and net loss widened from FY2023 to FY2025."
    slide = _slide(text, observations)
    issues = ClaimValidator().validate_slide(slide, observations)
    assert any(i.code == "direction_scope_ambiguous" and i.metric_name == "revenue" for i in issues)
    plan = PresentationPlan(title="Reported movements", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert repaired.slides[0].message == text
    assert not repairs
