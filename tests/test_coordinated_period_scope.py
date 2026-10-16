"""Coordinated claims retain their authored periods rather than chart endpoints."""

import pytest

from adaptive_document_agent.models import ChartPlan, Observation, PresentationPlan, PresentationSlide, SourceEvidence
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan


DATES = ("2021-12-31", "2022-12-31", "2023-12-31", "2024-06-30")


def _series(metric, values, *, periods=DATES):
    return [Observation(
        id=f"{metric}-{period}", metric_original=metric, value=value, raw_value=str(value),
        unit="count", unit_family="count", period=period, period_type="point_in_time",
        confidence=.9, evidence=[SourceEvidence(page=3, text=str(value),
                                                extraction_method="digital_table", confidence=.9)],
    ) for period, value in zip(periods, values, strict=True)]


def _observations():
    return [*_series("Order backlog", (10, 30, 20, 25)),
            *_series("Production capacity", (100, 160, 150, 140)),
            *_series("Installed equipment", (200, 260, 250, 240))]


def _slide(text, component="title"):
    return PresentationSlide(id="movements", slide_type="analysis",
                             observation_ids=[item.id for item in _observations()], **{
        component: [text] if component == "bullets" else text,
        **({"title": "Movements"} if component != "title" else {}),
    })


@pytest.mark.parametrize("component", ["title", "message", "bullets"])
@pytest.mark.parametrize("text", [
    "Order backlog rose from 2023-12-31 to 2024-06-30 while production capacity and installed equipment fell.",
    "From 2023-12-31 to 2024-06-30, production capacity and installed equipment fell.",
    "Production capacity fell from 2023-12-31 to 2024-06-30, and installed equipment fell.",
    "Production capacity and installed equipment fell from 2023-12-31 to 2024-06-30.",
])
def test_correct_coordinated_interior_interval_survives_validation_and_repair(text, component):
    observations = _observations()
    before = [item.model_dump() for item in observations]
    slide = _slide(text, component)
    assert not ClaimValidator().validate_slide(slide, observations)
    plan = PresentationPlan(title="Review", slides=[slide])
    snapshot = plan.model_dump()
    repaired, repairs = repair_presentation_plan(plan, observations)
    assert not repairs
    assert repaired.model_dump() == snapshot
    assert [item.model_dump() for item in observations] == before


@pytest.mark.parametrize("text", [
    "Order backlog rose from 2023-12-31 to 2024-06-30 while production capacity and installed equipment rose.",
    "From 2023-12-31 to 2024-06-30, production capacity and installed equipment rose.",
])
def test_wrong_shared_predicate_uses_both_metrics_and_the_exact_authored_interval(text):
    observations = _observations()
    slide = _slide(text)
    issues = ClaimValidator().validate_slide(slide, observations)
    assert {issue.metric_name for issue in issues} == {"production capacity", "installed equipment"}
    assert {(issue.start_period, issue.end_period) for issue in issues} == {
        ("2023-12-31", "2024-06-30")}
    repaired, repairs = repair_presentation_plan(PresentationPlan(title="Review", slides=[slide]), observations)
    assert repairs
    assert repaired.slides[0].title == text.rsplit("rose", 1)[0] + "fell."
    assert not ClaimValidator().validate_slide(repaired.slides[0], observations)


def test_distinct_local_ranges_override_inheritance():
    text = ("Order backlog rose from 2021-12-31 to 2022-12-31 while production capacity "
            "and installed equipment fell from 2023-12-31 to 2024-06-30.")
    assert not ClaimValidator().validate_slide(_slide(text), _observations())


def test_several_preceding_ranges_do_not_choose_a_convenient_interval():
    text = ("Order backlog rose from 2021-12-31 to 2022-12-31 while production capacity "
            "fell from 2023-12-31 to 2024-06-30, and installed equipment fell.")
    slide = _slide(text)
    issues = ClaimValidator().validate_slide(slide, _observations())
    assert any(issue.code == "direction_scope_ambiguous" and issue.metric_name == "installed equipment"
               for issue in issues)
    plan = PresentationPlan(title="Review", slides=[slide])
    repaired, repairs = repair_presentation_plan(plan, _observations())
    assert not repairs
    assert repaired.slides[0].title == text


@pytest.mark.parametrize("prefix", ["In 2024, ", "From 2020-12-31 to 2024-06-30, "])
def test_incomplete_or_missing_authored_endpoints_block_whole_series_fallback(prefix):
    text = prefix + "production capacity and installed equipment fell."
    slide = _slide(text)
    issues = ClaimValidator().validate_slide(slide, _observations())
    assert issues and all(issue.code == "direction_scope_ambiguous" for issue in issues)
    plan = PresentationPlan(title="Review", slides=[slide])
    assert not repair_presentation_plan(plan, _observations())[1]
    assert slide.title == text


@pytest.mark.parametrize("separator", [". ", "; ", "\n"])
def test_period_inheritance_does_not_cross_sentence_or_independent_section(separator):
    text = ("Order backlog rose from 2023-12-31 to 2024-06-30" + separator +
            "Installed equipment rose.")
    assert not ClaimValidator().validate_slide(_slide(text), _observations())


def test_shared_predicate_with_opposite_source_directions_requires_semantic_rewrite():
    observations = _observations()
    observations[-1].value = 270
    text = "From 2023-12-31 to 2024-06-30, production capacity and installed equipment fell."
    slide = _slide(text)
    issues = ClaimValidator().validate_slide(slide, observations)
    assert len(issues) == 1
    assert issues[0].code == "directional_contradiction"
    assert issues[0].metric_name == "installed equipment"
    assert issues[0].expected_direction == "INCREASED"
    assert issues[0].repair_blocked_reason
    repaired, repairs = repair_presentation_plan(PresentationPlan(title="Review", slides=[slide]), observations)
    assert not repairs
    assert repaired.slides[0].title == text


def test_summary_and_detail_use_authored_range_even_when_charts_display_longer_history():
    observations = _observations()
    text = ("Order backlog rose from 2023-12-31 to 2024-06-30 while production capacity "
            "and installed equipment rose.")
    charts = [ChartPlan(id=f"chart-{index}", title=metric, chart_type="line", question="What changed?",
                        observation_ids=[item.id for item in observations if item.metric_original == metric])
              for index, metric in enumerate(("Order backlog", "Production capacity", "Installed equipment"))]
    summary = PresentationSlide(id="summary", slide_type="executive_summary", title="Summary",
                                bullets=[text], observation_ids=[item.id for item in observations],
                                bullet_observation_ids=[[item.id for item in observations]])
    detail = _slide(text)
    detail.chart_ids = [chart.id for chart in charts]
    plan = PresentationPlan(title="Review", slides=[summary, detail])
    snapshot = [item.model_dump() for item in observations]
    issues = ClaimValidator().validate_plan(plan, observations, charts)
    assert len(issues) == 4
    assert {(issue.start_period, issue.end_period) for issue in issues} == {
        ("2023-12-31", "2024-06-30")}
    repaired, repairs = repair_presentation_plan(plan, observations, charts)
    assert len(repairs) == 2
    expected = text.rsplit("rose", 1)[0] + "fell."
    assert repaired.slides[0].bullets == [expected]
    assert repaired.slides[1].title == expected
    assert not ClaimValidator().validate_plan(repaired, observations, charts)
    assert [item.model_dump() for item in observations] == snapshot


@pytest.mark.parametrize("metric,values,verb,percentage", [
    ("Net loss", (-10, -30, -20, -15), "narrowed", False),
    ("Operating expenses", (-10, -30, -20, -15), "decreased", False),
    ("Service completion ratio", (40, 20, 25, 30), "rose", True),
])
def test_inherited_range_retains_signed_expense_loss_and_ratio_semantics(metric, values, verb, percentage):
    periods = ("FY2021", "FY2022", "FY2023", "FY2024")
    observations = _series(metric, values, periods=periods)
    for item in observations:
        item.unit, item.unit_family = ("percent", "percentage") if percentage else ("currency", "currency")
        item.currency = None if percentage else "USD"
        item.raw_unit = "%" if percentage else "USD million"
        item.period_type = "fiscal_year"
    text = f"From FY2023 to FY2024, {metric} {verb}."
    slide = _slide(text)
    slide.observation_ids = [item.id for item in observations]
    assert not ClaimValidator().validate_slide(slide, observations)
    repaired, repairs = repair_presentation_plan(PresentationPlan(title="Review", slides=[slide]), observations)
    assert not repairs
    assert repaired.slides[0].title == text
