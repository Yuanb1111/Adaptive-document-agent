import pytest

from adaptive_document_agent.agent.presentation_planner import PresentationPlanner
from adaptive_document_agent.models import CompanyProfile, PresentationPlan, PresentationSlide
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator
from tests.test_pptx_export import _result


def test_presentation_plan_validator_rejects_unknown_fact_references() -> None:
    result = _result()
    plan = PresentationPlan(
        title="Invalid plan",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="analysis",
                slide_type="analysis",
                title="Unsupported conclusion",
                section_title="Financial Performance",
                message="This message has no retained source.",
                observation_ids=["missing-observation"],
                source_pages=[234],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Source data"),
        ],
    )

    with pytest.raises(ValueError, match="unknown observations"):
        PresentationPlanValidator().validate(plan, result)


def test_presentation_plan_validator_rejects_invented_numeric_claims() -> None:
    result = _result()
    plan = PresentationPlan(
        title="Invalid numeric claim",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(
                id="summary",
                slide_type="executive_summary",
                title="Revenue increased by 999%",
                insight_ids=["insight-1"],
                source_pages=[234],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Source data"),
        ],
    )

    with pytest.raises(ValueError, match="unsupported numeric claims"):
        PresentationPlanValidator().validate(plan, result)


def test_presentation_plan_validator_accepts_company_excerpt_pages_and_grouped_numbers() -> None:
    result = _result()
    plan = PresentationPlan(
        title="Supported plan",
        company=CompanyProfile(
            name="Example Automation",
            one_line_description="Source-supported company description.",
            source_pages=[8],
        ),
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(
                id="overview",
                slide_type="company_overview",
                title="Company at a Glance",
                observation_ids=["revenue-2023"],
                source_pages=[8],
            ),
            PresentationSlide(
                id="summary",
                slide_type="executive_summary",
                title="Revenue reached 267 025 in the first retained period",
                observation_ids=["revenue-2023"],
                source_pages=[234],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Source data"),
        ],
    )

    assert PresentationPlanValidator().validate(plan, result) is plan
    assert PresentationPlanValidator._numbers("659 336 034; 754,257,120; 1’234") == {
        "659336034",
        "754257120",
        "1234",
    }


def test_presentation_planner_repairs_one_semantically_invalid_plan() -> None:
    result = _result()
    invalid = {
        "title": "Review",
        "slides": [
            {"id": "cover", "slide_type": "cover", "title": "Review"},
            {"id": "overview", "slide_type": "company_overview", "title": "Company at a Glance"},
            {
                "id": "summary",
                "slide_type": "executive_summary",
                "title": "Revenue increased by 999%",
                "insight_ids": ["insight-1"],
                "source_pages": [234],
            },
            {"id": "quality", "slide_type": "data_quality", "title": "Data quality"},
            {"id": "appendix", "slide_type": "appendix", "title": "Source data"},
        ],
    }
    repaired = {
        **invalid,
        "slides": [
            *invalid["slides"][:2],
            {
                "id": "summary",
                "slide_type": "executive_summary",
                "title": "Revenue increased across the retained period",
                "insight_ids": ["insight-1"],
                "source_pages": [234],
            },
            *invalid["slides"][3:],
        ],
    }
    client = MockLLMClient([invalid, repaired])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))

    plan = PresentationPlanner(gateway).plan(result)

    assert plan.slides[2].title == "Revenue increased across the retained period"
    assert len(client.calls) == 2
    assert "failed deterministic validation" in client.calls[1][2]["content"]
