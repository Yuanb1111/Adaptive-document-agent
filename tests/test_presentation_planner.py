import pytest

from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.agent.presentation_plan_repairer import PresentationPlanRepairer
from adaptive_document_agent.agent.presentation_planner import PresentationPlanner
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.models import (
    AnalysisResult,
    AnalysisTask,
    CompanyFact,
    CompanyProfile,
    Observation,
    PresentationPlan,
    PresentationSlide,
    PresentationVisualBlock,
    SourceEvidence,
)
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


def test_presentation_plan_repairer_cleans_unsupported_references_and_numbers() -> None:
    result = _result()
    plan = PresentationPlan(
        title="Dirty AI plan",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(
                id="summary",
                slide_type="executive_summary",
                title="Revenue was reported. Invented figure 999,999,999.",
                message="Valid statement. Another unsupported 888,888 number.",
                bullets=["Supported bullet", "Invented 777,777 claim"],
                observation_ids=["revenue-2023", "nonexistent-obs-id"],
                chart_ids=["chart-1", "nonexistent-chart-id"],
                insight_ids=["insight-1", "nonexistent-insight-id"],
                source_pages=[234, 999],
            ),
            PresentationSlide(
                id="empty_analysis",
                slide_type="analysis",
                title="Empty",
                observation_ids=["nonexistent-only"],
            ),
            PresentationSlide(
                id="quality",
                slide_type="data_quality",
                title="Data Quality",
                section_title="",
            ),
            PresentationSlide(id="appendix", slide_type="appendix", title="Source Data"),
        ],
    )
    repaired = PresentationPlanRepairer().repair(plan, result)
    assert PresentationPlanValidator().validate(repaired, result) is repaired
    summary_slide = next(s for s in repaired.slides if s.slide_type == "executive_summary")
    assert 999 not in summary_slide.source_pages
    assert "nonexistent-obs-id" not in summary_slide.observation_ids
    assert "nonexistent-chart-id" not in summary_slide.chart_ids
    assert not any(s.id == "empty_analysis" for s in repaired.slides)
    quality_slide = next(s for s in repaired.slides if s.slide_type == "data_quality")
    assert quality_slide.section_title == "Data quality"


def test_presentation_plan_repairer_merges_duplicates_and_limits_charts() -> None:
    result = _result()
    plan = PresentationPlan(
        title="Duplicates and extra charts",
        company=CompanyProfile(
            name="Test Corp",
            products=["Widget A", "Widget B", "widget a"],
            segments=["Hardware", "Software", "hardware"],
            geographies=["Asia", "asia", "Europe"],
            key_facts=[
                CompanyFact(label="CEO", value="Alice", source_pages=[8]),
                CompanyFact(label="ceo", value="Alice", source_pages=[8]),
            ],
            source_pages=[8],
        ),
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="analysis_1",
                slide_type="analysis",
                title="Analysis 1",
                section_title="Financials",
                message="Evidence analysis.",
                chart_ids=["chart-1", "chart-1"],
                visual_blocks=[
                    PresentationVisualBlock(role="hero", title="Block 1", chart_ids=["chart-1"], chart_type="table"),
                    PresentationVisualBlock(role="supporting", title="Block 2", chart_ids=["chart-1"], chart_type="scatter"),
                ],
                source_pages=[234],
            ),
            PresentationSlide(
                id="risks",
                slide_type="risks",
                title="Risks",
                section_title="Key risks",
                message="Key risk observation.",
                bullets=["Risk A", "risk a"],
                observation_ids=["revenue-2023"],
                source_pages=[234],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Source Data"),
        ],
    )
    repaired = PresentationPlanRepairer().repair(plan, result)
    assert len(repaired.company.products) == 2
    assert len(repaired.company.segments) == 2
    assert len(repaired.company.geographies) == 2
    assert len(repaired.company.key_facts) == 1
    analysis_slide = next(s for s in repaired.slides if s.id == "analysis_1")
    assert analysis_slide.visual_blocks[0].chart_type is None
    assert len(analysis_slide.chart_ids) <= 3
    risk_slide = next(s for s in repaired.slides if s.slide_type == "risks")
    assert len(risk_slide.bullets) == 1


def test_presentation_plan_recovery_fallback_builds_complete_modern_structure() -> None:
    result = _result()
    fallback_plan = PresentationPlanRecovery().fallback(result)
    slide_types = [s.slide_type for s in fallback_plan.slides]
    assert slide_types[0] == "cover"
    assert slide_types[1] == "company_overview"
    assert slide_types[2] == "executive_summary"
    assert "analysis" in slide_types
    assert slide_types[-2] == "data_quality"
    assert slide_types[-1] == "appendix"
    assert fallback_plan.company.name == "Company overview"


def test_chart_planner_prioritizes_core_metrics_over_peripheral_items() -> None:
    from adaptive_document_agent.agent.chart_planner import ChartPlanner

    obs_core = [
        Observation(
            id=f"rev_{year}",
            metric_original="Revenue",
            metric_canonical="revenue",
            value=float(year * 100),
            raw_value=str(year * 100),
            period=str(year),
            confidence=0.95,
            evidence=[SourceEvidence(page=1, extraction_method="table", confidence=0.95)],
        )
        for year in (2022, 2023, 2024, 2025)
    ]
    obs_peripheral = [
        Observation(
            id=f"tax_{year}",
            metric_original="Prepaid income tax",
            metric_canonical="prepaid_income_tax",
            value=float(year * 2),
            raw_value=str(year * 2),
            period=str(year),
            confidence=0.9,
            evidence=[SourceEvidence(page=2, extraction_method="table", confidence=0.9)],
        )
        for year in (2023, 2024)
    ]
    index = DocumentIndex([*obs_core, *obs_peripheral])
    tasks = [
        AnalysisTask(
            id="task_tax",
            title="Prepaid tax change",
            description="Prepaid tax change",
            expected_output="percentage",
            analysis_type="percentage_change",
            reason="Check tax",
            required_metrics=["prepaid_income_tax"],
            observation_query={"observation_ids": [o.id for o in obs_peripheral]},
        ),
        AnalysisTask(
            id="task_rev",
            title="Revenue change",
            description="Revenue change",
            expected_output="percentage",
            analysis_type="percentage_change",
            reason="Check revenue",
            required_metrics=["revenue"],
            observation_query={"observation_ids": [o.id for o in obs_core]},
        ),
    ]
    results = [
        AnalysisResult(task_id="task_tax", title="Prepaid tax change", result=0.1, evidence=[obs_peripheral[0].evidence[0]]),
        AnalysisResult(task_id="task_rev", title="Revenue change", result=0.2, evidence=[obs_core[0].evidence[0]]),
    ]
    charts = ChartPlanner().plan(tasks, results, index, analysis_focus="revenue trend", maximum=2)
    assert len(charts) == 2
    assert charts[0].analysis_task_id == "task_rev"


def test_extract_presentation_errors_formats_clean_bullets() -> None:
    from adaptive_document_agent.ui.technical import _extract_presentation_errors

    raw_error = (
        "The AI presentation plan could not be retained. Reason: Presentation plan validation failed. "
        "Initial reason: Invalid presentation plan: slide_analysis_cash cites unsupported page 525; "
        "unsupported numeric claim: 1,257,120; chart_type area is unavailable; section_title is missing. "
        "AI repair reason: repair error. Deterministic repair reason: none"
    )
    errors = _extract_presentation_errors(raw_error)
    assert any("slide_analysis_cash cites unsupported page 525" in e for e in errors)
    assert any("unsupported numeric claim: 1,257,120" in e for e in errors)
    assert any("chart_type area is unavailable" in e for e in errors)
    assert any("section_title is missing" in e for e in errors)


def test_presentation_plan_repairer_preserves_usable_charts_when_ai_slides_have_hallucinated_ids() -> None:
    result = _result()
    # Simulate an AI plan with invalid / hallucinated chart and observation IDs
    plan = PresentationPlan(
        title="AI Plan With Hallucinated IDs",
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Review"),
            PresentationSlide(id="overview", slide_type="company_overview", title="Company at a Glance"),
            PresentationSlide(id="summary", slide_type="executive_summary", title="Executive Summary"),
            PresentationSlide(
                id="slide_analysis_bad",
                slide_type="analysis",
                title="Revenue Overview",
                section_title="Financial Performance",
                message="Revenue analysis statement.",
                chart_ids=["chart_hallucinated_999"],
                observation_ids=["obs_hallucinated_888"],
            ),
            PresentationSlide(id="quality", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="appendix", slide_type="appendix", title="Appendix"),
        ],
    )

    repaired = PresentationPlanRepairer().repair(plan, result)
    assert PresentationPlanValidator().validate(repaired, result) is repaired

    # Ensure the presentation retains analysis slides and charts
    analysis_slides = [s for s in repaired.slides if s.slide_type == "analysis"]
    assert len(analysis_slides) >= 1
    total_charts = [
        cid
        for s in analysis_slides
        for cid in (*s.chart_ids, *(c for b in s.visual_blocks for c in b.chart_ids))
    ]
    assert "chart-1" in total_charts
