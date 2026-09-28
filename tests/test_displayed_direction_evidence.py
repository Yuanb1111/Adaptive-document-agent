"""Coverage records must not expand a displayed claim's comparison periods."""

import copy

import pytest

from adaptive_document_agent.models import ChartPlan, PresentationPlan, PresentationSlide
from adaptive_document_agent.validation.claim_validator import ClaimValidator, repair_presentation_plan
from adaptive_document_agent.validation.cross_slide_validator import CrossSlideValidator
from tests.test_mixed_period_claim_validation import _sample_revenue_mixed_observations


def _sample():
    observations = _sample_revenue_mixed_observations()
    chart = ChartPlan(id="annual", title="Annual revenue", chart_type="bar",
                      question="What changed?", observation_ids=[item.id for item in observations[:2]])
    title = "Revenue increased."
    plan = PresentationPlan(title="Review", slides=[
        PresentationSlide(id="summary", slide_type="executive_summary", title="Summary",
                          bullets=[title], observation_ids=[item.id for item in observations],
                          bullet_observation_ids=[[item.id for item in observations]]),
        PresentationSlide(id="detail", slide_type="analysis", title=title, chart_ids=[chart.id],
                          observation_ids=[item.id for item in observations]),
    ])
    return plan, observations, [chart]


@pytest.mark.parametrize("interim_end", [65, 40])
def test_matching_summary_and_analysis_use_only_displayed_comparable_periods(interim_end):
    plan, observations, charts = _sample()
    observations[-1].value = interim_end
    observations[-1].raw_value = str(interim_end)
    raw, refs = copy.deepcopy(observations), [list(slide.observation_ids) for slide in plan.slides]
    assert not ClaimValidator().validate_plan(plan, observations, charts)
    original = plan.model_dump()
    _, repairs = repair_presentation_plan(plan, observations, charts)
    assert not repairs
    assert plan.model_dump() == original
    assert observations == raw
    assert refs == [slide.observation_ids for slide in plan.slides]


def test_wrong_displayed_direction_is_still_rejected_and_repaired_for_both_copies():
    plan, observations, charts = _sample()
    observations[1].value, observations[1].raw_value = 80, "80"
    issues = ClaimValidator().validate_plan(plan, observations, charts)
    assert {issue.slide_id for issue in issues if issue.code == "directional_contradiction"} == {"summary", "detail"}
    repair_presentation_plan(plan, observations, charts)
    assert "decreased" in plan.slides[1].title
    assert "decreased" in plan.slides[0].bullets[0]
    assert "6M" not in plan.slides[1].title + plan.slides[0].bullets[0]


def test_independent_interim_bullet_keeps_its_own_bound_scope():
    plan, observations, charts = _sample()
    summary = plan.slides[0]
    summary.bullets = ["Revenue declined from 6M2020 to 6M2021."]
    summary.bullet_observation_ids = [[item.id for item in observations[2:]]]
    issues = ClaimValidator().validate_plan(plan, observations, charts)
    assert any(issue.slide_id == "summary" and issue.code == "directional_contradiction" for issue in issues)
    assert not any(issue.slide_id == "detail" for issue in issues)


def test_cross_slide_summary_only_pass_retains_full_plan_display_context():
    plan, observations, charts = _sample()
    before = plan.model_dump()
    validator = CrossSlideValidator(plan, observations, charts)
    assert not validator._check_summary_vs_detail_consistency(auto_repair=True)
    assert plan.model_dump() == before


def test_independent_analysis_bullet_can_discuss_separate_evidence():
    plan, observations, charts = _sample()
    detail = plan.slides[1]
    detail.bullets = ["Revenue declined from 6M2020 to 6M2021."]
    detail.bullet_observation_ids = [[item.id for item in observations[2:]]]
    issues = ClaimValidator().validate_plan(plan, observations, charts)
    assert any(issue.slide_id == "detail" and issue.target_component == "bullet"
               and issue.code == "directional_contradiction" for issue in issues)
    assert not any(issue.slide_id == "detail" and issue.target_component == "title" for issue in issues)


@pytest.mark.parametrize("scope", [{"entity": "Separate subsidiary"}, {"currency": "USD"},
                                  {"unit": "count"}, {"category_dimensions": {"region": "Europe"}}])
def test_same_metric_other_entity_or_measure_scope_is_not_discarded(scope):
    from adaptive_document_agent.validation.presentation_direction_evidence import _on_displayed_series
    _, observations, _ = _sample()
    separate = [item.model_copy(update={"id": "other-" + item.id, **scope}) for item in observations[2:]]
    selected = _on_displayed_series([*observations, *separate], {item.id for item in observations[:2]})
    assert {item.id for item in selected} == {item.id for item in [*observations[:2], *separate]}


def test_conflicting_same_period_and_other_source_records_remain_for_alignment():
    from adaptive_document_agent.validation.presentation_direction_evidence import _on_displayed_series
    _, observations, _ = _sample()
    conflict = observations[0].model_copy(update={"id": "conflict", "value": 999})
    other = observations[-1].model_copy(update={"id": "other-source", "table_id": "other"})
    selected = _on_displayed_series([*observations, conflict, other], {item.id for item in observations[:2]})
    assert {item.id for item in selected} == {observations[0].id, observations[1].id, conflict.id, other.id}


def test_undisplayed_intermediate_period_cannot_hide_a_reversal():
    from adaptive_document_agent.validation.presentation_direction_evidence import _on_displayed_series
    _, observations, _ = _sample()
    last = observations[1].model_copy(update={"id": "last", "period": "FY2021", "value": 90})
    selected = _on_displayed_series([*observations[:2], last], {observations[0].id, last.id})
    assert {item.id for item in selected} == {observations[0].id, observations[1].id, last.id}
