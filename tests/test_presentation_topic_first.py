"""A full series inventory selects questions before the chart quota is applied."""

import json
import io

import pytest
from pptx import Presentation

from adaptive_document_agent.agent.chart_planner import ChartPlanner
from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.agent.presentation_topic_selector import PresentationTopicSelector, series_directory
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import PresentationPlan, PresentationSlide, PresentationTopic, PresentationTopicSelection
from adaptive_document_agent.models.page import DocumentPage
from adaptive_document_agent.services.pptx_export import build_presentation
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_pptx_export import _result


def test_topic_selector_receives_complete_series_directory_and_exact_ids() -> None:
    result = _result()
    directory, _ = series_directory(result)
    selected_id = directory[0]["id"]

    class Gateway:
        def generate_structured(self, messages, response_model, **kwargs):
            self.messages = messages
            return response_model.model_validate({
                "topics": [{"id": "growth", "title": "Revenue movement",
                            "question": "How did revenue move?",
                            "rationale": "The source reports comparable annual revenue.",
                            "series_ids": [selected_id]}],
            })

    gateway = Gateway()
    selection = PresentationTopicSelector(gateway).select(result)
    payload = json.loads(gateway.messages[-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert {row[0] for row in payload["all_extracted_series"]} == {item["id"] for item in directory}
    assert selection.topics[0].series_ids == [selected_id]


def test_topic_selector_keeps_background_excerpts_outside_primary_analysis(monkeypatch) -> None:
    from adaptive_document_agent.services.company_discovery import CompanyProfileDiscovery

    result = _result()
    result.document.pages = [
        DocumentPage(page_number=1, text="Summary: products and applications"),
        DocumentPage(page_number=234, text="Financial Information: reported revenue"),
    ]
    monkeypatch.setattr(
        CompanyProfileDiscovery, "rank_profile_pages",
        staticmethod(lambda *args, **kwargs: [1, 234]),
    )
    selected_id = series_directory(result)[0][0]["id"]

    class Gateway:
        def generate_structured(self, messages, response_model, **kwargs):
            self.messages = messages
            return response_model(topics=[PresentationTopic(
                id="growth", title="Revenue movement", question="How did revenue move?",
                rationale="Comparable annual revenue is available.", series_ids=[selected_id],
            )])

    gateway = Gateway()
    PresentationTopicSelector(gateway).select(result)
    payload = json.loads(gateway.messages[-1]["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert payload["background_page_excerpts"] == [
        {"page": 1, "text": "Summary: products and applications"}
    ]


def test_topic_selector_rejects_unknown_evidence_id() -> None:
    with pytest.raises(ValueError, match="unknown"):
        PresentationTopicSelector._validate(
            PresentationTopicSelection(topics=[PresentationTopic(
                id="bad", title="Unknown", question="What changed?",
                rationale="Candidate topic", series_ids=["made_up"])]),
            {},
        )


def test_topic_selector_rejects_background_metric_as_primary_evidence() -> None:
    result = _result()
    outside = [item.model_copy(deep=True) for item in result.observations]
    for item in outside:
        for evidence in item.evidence:
            evidence.page = 1
    selection = PresentationTopicSelection(topics=[PresentationTopic(
        id="background", title="Business background", question="What changed?",
        rationale="This is background evidence.", series_ids=["background-series"],
    )])
    with pytest.raises(ValueError, match="outside the primary analysis scope"):
        PresentationTopicSelector._validate(
            selection, {"background-series": outside}, primary_pages={234},
        )


def test_topic_selector_repairs_unsupported_numeric_claim_once() -> None:
    result = _result()
    directory, _ = series_directory(result)
    series_id = directory[0]["id"]

    class Gateway:
        calls = 0

        def generate_structured(self, messages, response_model, **kwargs):
            self.calls += 1
            return response_model(topics=[PresentationTopic(
                id="growth", title="Revenue reached 999", question="How did revenue move?",
                rationale="Comparable annual revenue is available.", series_ids=[series_id],
            )]) if self.calls == 1 else response_model(topics=[PresentationTopic(
                id="growth", title="Revenue movement", question="How did revenue move?",
                rationale="Comparable annual revenue is available.", series_ids=[series_id],
            )])

    gateway = Gateway()
    assert PresentationTopicSelector(gateway).select(result).topics[0].title == "Revenue movement"
    assert gateway.calls == 2


def test_requested_topic_series_are_not_lost_to_generic_chart_limit() -> None:
    result = _result()
    revenue = result.observations
    orders = [item.model_copy(deep=True) for item in revenue]
    for item in orders:
        item.id = item.id.replace("revenue", "orders")
        item.metric_original = "Orders"
        item.metric_canonical = "orders"
        item.unit = "count"
        item.raw_unit = "orders"
        item.currency = None
    charts = ChartPlanner().plan(
        [], [], DocumentIndex([*revenue, *orders]), maximum=1,
        requested_series=[revenue, orders],
    )
    assert len(charts) >= 2
    assert {identifier for chart in charts[:2] for identifier in chart.observation_ids} == {
        item.id for item in [*revenue, *orders]
    }
    only_selected = ChartPlanner().plan(
        [], [], DocumentIndex([*revenue, *orders]), maximum=10,
        requested_series=[orders], only_requested=True,
    )
    assert {identifier for chart in only_selected for identifier in chart.observation_ids} == {
        item.id for item in orders
    }


def test_failed_slide_writing_can_retain_selected_question() -> None:
    result = _result()
    directory, lookup = series_directory(result)
    selected_id = directory[0]["id"]
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id="growth", title="Revenue movement", question="How did revenue move?",
        rationale="The source reports a comparable annual revenue series.",
        series_ids=[selected_id],
    )])
    result.charts = ChartPlanner().plan(
        [], [], DocumentIndex(result.observations), maximum=1,
        requested_series=[lookup[selected_id]],
    )
    plan = PresentationPlanRecovery().from_selected_topics(result)
    assert plan.planning_origin == "topic_recovery"
    assert plan.themes[0].id == "growth"
    assert plan.slides[3].chart_ids
    assert plan.slides[3].analytical_question == "How did revenue move?"
    PresentationPlanValidator().validate(plan, result)


def test_sourced_company_identity_cannot_be_called_unnamed() -> None:
    result = _result()
    plan = PresentationPlanRecovery().fallback(result)
    plan.company.name = "DOBOT"
    plan.company.source_pages = [1]
    plan.company.one_line_description = "Unnamed issuer with robotics products"
    with pytest.raises(ValueError, match="contradicts the sourced company identity"):
        PresentationPlanValidator().validate(plan, result)


def test_thematic_appendix_keeps_selected_evidence_without_unrelated_conflicts() -> None:
    result = _result()
    directory, lookup = series_directory(result)
    selected_id = directory[0]["id"]
    result.presentation_topics = PresentationTopicSelection(topics=[PresentationTopic(
        id="growth", title="Revenue movement", question="How did revenue move?",
        rationale="Comparable annual revenue is available.", series_ids=[selected_id],
    )])
    result.charts = ChartPlanner().plan(
        [], [], DocumentIndex(result.observations), requested_series=[lookup[selected_id]],
        only_requested=True,
    )
    result.presentation_plan = PresentationPlanRecovery().from_selected_topics(result)
    conflicting = [item.model_copy(deep=True) for item in result.observations[:2]]
    for ordinal, item in enumerate(conflicting):
        item.id = f"unrelated-{ordinal}"
        item.metric_original = "Others"
        item.metric_canonical = "Others"
        item.period = "FY2023"
        item.value = float(ordinal + 1)
        item.raw_value = str(ordinal + 1)
    result.observations.extend(conflicting)
    assert build_presentation(result).startswith(b"PK")


def test_sourced_conclusion_follows_appendix_without_generic_signoff() -> None:
    result = _result()
    result.presentation_plan = PresentationPlan(title="Revenue review", slides=[
        PresentationSlide(id="cover", slide_type="cover", title="Revenue review"),
        PresentationSlide(id="company", slide_type="company_overview", title="Document at a Glance"),
        PresentationSlide(id="summary", slide_type="executive_summary", title="Summary",
                          insight_ids=["insight-1"], source_pages=[234]),
        PresentationSlide(id="analysis", slide_type="analysis", title="Revenue movement",
                          section_title="Performance", message="How did revenue move?",
                          chart_ids=["chart-1"], source_pages=[234]),
        PresentationSlide(id="close", slide_type="risks", title="Conclusions and Watch Items",
                          section_title="Conclusions", message="Indicators to monitor.",
                          bullets=["Monitor whether the revenue trend continues."],
                          insight_ids=["insight-1"], source_pages=[234]),
        PresentationSlide(id="quality", slide_type="data_quality", title="Data quality"),
        PresentationSlide(id="appendix", slide_type="appendix", title="Source data"),
    ])
    deck = Presentation(io.BytesIO(build_presentation(result)))
    last_text = " ".join(shape.text for shape in deck.slides[-1].shapes if shape.has_text_frame)
    assert "Conclusions and Watch Items" in last_text
    assert "Monitor whether the revenue trend continues" in last_text
    assert "THANK YOU" not in last_text
