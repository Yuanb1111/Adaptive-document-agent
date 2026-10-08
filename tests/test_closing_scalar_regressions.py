"""A scalar calculation must not become an input metric's reported level."""

from copy import deepcopy
import json

import pytest

from adaptive_document_agent.agent.insight_generator import InsightGenerator
from adaptive_document_agent.agent.presentation_closing_validation import closing_claim_errors, withhold_cached_closing_claims
from adaptive_document_agent.agent.topic_plan_compiler import compile_topic_plan
from adaptive_document_agent.agent.presentation_topic_selector import series_directory
from adaptive_document_agent.models import AnalysisResult, PresentationPlan, PresentationSlide, PresentationTopic, PresentationTopicSelection
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_segmented_direction_claims import _series
from tests.test_pptx_export import _result


@pytest.mark.parametrize("metric,unit", [("Inventory turnover days", "days"), ("Service hours", "hours"),
                                         ("Survey responses", "responses")])
def test_scalar_fallback_retains_reported_inputs_without_guessing_output_unit(metric, unit):
    observations = _series(metric, [248, 256, 304])
    for item in observations:
        item.unit, item.raw_unit, item.currency = unit, unit, None
    result = AnalysisResult(task_id="change", title=f"{metric} growth", result=22.58064516129032,
                            input_observation_ids=[o.id for o in observations],
                            evidence=observations[0].evidence, confidence=.9)
    before = deepcopy(observations)
    insight = InsightGenerator().generate([result], observations)[0]
    assert "22.58" not in insight.narrative and "stood at" not in insight.narrative
    assert all(str(value) in insight.narrative for value in (248, 256, 304))
    assert all(o.period in insight.narrative for o in observations)
    assert insight.kind == "reported_fact" and insight.result_ids == ["change"]
    assert observations == before


def test_closing_rejects_untyped_growth_as_level_but_accepts_explicit_growth_rate():
    result = _result()
    result.observations = _series("Inventory turnover days", [248, 256, 304])
    for item in result.observations:
        item.unit, item.raw_unit, item.currency = "days", "days", None
    assert closing_claim_errors("Inventory turnover days stood at 22.6.", result.observations, result)
    assert not closing_claim_errors("Inventory turnover days increased 22.6% from FY2023 to FY2025.",
                                    result.observations, result)


def test_cached_closing_withdrawal_preserves_safe_sibling_and_all_raw_results():
    result = _result()
    ids = [o.id for o in result.observations]
    unsafe, safe = "Revenue stood at 95.4.", "Monitor the next reported revenue."
    result.presentation_plan = PresentationPlan(title="Review", planning_origin="fallback", slides=[
        PresentationSlide(id="closing", slide_type="risks", title="Conclusions", bullets=[unsafe, safe],
                          observation_ids=ids, bullet_observation_ids=[ids, ids])])
    raw = result.model_dump(include={"observations", "insights", "analysis_results"})
    assert withhold_cached_closing_claims(result, result.presentation_plan)
    slide = result.presentation_plan.slides[0]
    assert slide.bullets == [safe] and slide.bullet_observation_ids == [ids]
    assert unsafe in json.loads(result.validation_warnings[-1].message)["statement"]
    assert result.model_dump(include=set(raw)) == raw
    assert not withhold_cached_closing_claims(result, result.presentation_plan)


def test_scoped_endpoint_error_cannot_block_independent_period_scope_recovery():
    result = _result()
    result.profile.analysis_page_ranges = [(1, 300)]
    turnover = _series("Inventory turnover days", [248, 256, 304])
    stock = _series("Inventory", [500, 600, 700])
    for item in turnover + stock:
        item.evidence[0].page = 1
    for item in turnover:
        item.unit, item.raw_unit, item.currency = "days", "days", None
    result.observations.extend(turnover + stock)
    _, lookup = series_directory(result)
    def sid(metric):
        return next(key for key, items in lookup.items() if items[0].metric_original == metric)
    revenue = PresentationTopic(id="revenue", title="Revenue", question="How did revenue change?",
        rationale="Reported periods", series_ids=[sid("Revenue")], takeaway="Revenue increased through FY2025.")
    inventory = PresentationTopic(id="inventory", title="Inventory turnover days",
        question="How did inventory turnover days change?", rationale="Reported periods",
        series_ids=[sid("Inventory turnover days")],
        takeaway="Inventory increased from 248 in FY2023 to 304 in FY2025.")
    result.presentation_topics = PresentationTopicSelection(topics=[revenue, inventory])
    raw = result.model_dump(include={"observations", "insights", "analysis_results", "presentation_topics"})
    plan = compile_topic_plan(result)
    assert {s.title for s in plan.slides if s.slide_type == "analysis"} == {revenue.question, inventory.question}
    assert len(plan.themes) == 2 and plan.editorial_status == "needs_review"
    assert result.model_dump(include=set(raw)) == raw
    assert PresentationPlanValidator().validate(plan, result) is plan
