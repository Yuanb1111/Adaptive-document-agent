import pytest

from adaptive_document_agent.models import PresentationPlan, PresentationSlide
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
