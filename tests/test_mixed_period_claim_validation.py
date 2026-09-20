from __future__ import annotations

import pytest

from adaptive_document_agent.agent.chart_planner import ChartPlanner
from adaptive_document_agent.document_model import DocumentIndex
from adaptive_document_agent.document_model.chartability import score_chartability
from adaptive_document_agent.models import (
    AnalysisResult,
    AnalysisTask,
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    SourceEvidence,
)
from adaptive_document_agent.services.qa_reporter import (
    CriticalQAError,
    run_comprehensive_qa,
)
from adaptive_document_agent.validation.claim_validator import (
    ClaimValidator,
    partition_compatible_series,
    repair_presentation_plan,
    repair_slide_claims,
)


def _ev(page: int = 1, text: str = "val") -> list[SourceEvidence]:
    return [SourceEvidence(page=page, text=text, extraction_method="digital_table", confidence=0.95)]


def _sample_revenue_mixed_observations() -> list[Observation]:
    return [
        Observation(
            id="rev_fy19",
            metric_original="Revenue",
            metric_canonical="revenue",
            value=100.0,
            raw_value="100.0",
            period="FY2019",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "100.0"),
            confidence=0.95,
        ),
        Observation(
            id="rev_fy20",
            metric_original="Revenue",
            metric_canonical="revenue",
            value=120.0,
            raw_value="120.0",
            period="FY2020",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "120.0"),
            confidence=0.95,
        ),
        Observation(
            id="rev_6m20",
            metric_original="Revenue",
            metric_canonical="revenue",
            value=50.0,
            raw_value="50.0",
            period="6M2020",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "50.0"),
            confidence=0.95,
        ),
        Observation(
            id="rev_6m21",
            metric_original="Revenue",
            metric_canonical="revenue",
            value=65.0,
            raw_value="65.0",
            period="6M2021",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "65.0"),
            confidence=0.95,
        ),
    ]


def _sample_loss_mixed_observations() -> list[Observation]:
    return [
        Observation(
            id="loss_fy19",
            metric_original="Adjusted Net Loss",
            metric_canonical="adjusted_net_loss",
            value=-100.0,
            raw_value="-100.0",
            period="FY2019",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "-100.0"),
            confidence=0.95,
        ),
        Observation(
            id="loss_fy20",
            metric_original="Adjusted Net Loss",
            metric_canonical="adjusted_net_loss",
            value=-60.0,
            raw_value="-60.0",
            period="FY2020",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "-60.0"),
            confidence=0.95,
        ),
        Observation(
            id="loss_6m20",
            metric_original="Adjusted Net Loss",
            metric_canonical="adjusted_net_loss",
            value=-25.0,
            raw_value="-25.0",
            period="6M2020",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "-25.0"),
            confidence=0.95,
        ),
        Observation(
            id="loss_6m21",
            metric_original="Adjusted Net Loss",
            metric_canonical="adjusted_net_loss",
            value=-15.0,
            raw_value="-15.0",
            period="6M2021",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "-15.0"),
            confidence=0.95,
        ),
    ]


def _sample_rd_expenses_mixed_observations() -> list[Observation]:
    return [
        Observation(
            id="rd_fy19",
            metric_original="R&D Expenses",
            metric_canonical="research_and_development_expenses",
            value=40.0,
            raw_value="40.0",
            period="FY2019",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "40.0"),
            confidence=0.95,
        ),
        Observation(
            id="rd_fy20",
            metric_original="R&D Expenses",
            metric_canonical="research_and_development_expenses",
            value=55.0,
            raw_value="55.0",
            period="FY2020",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "55.0"),
            confidence=0.95,
        ),
        Observation(
            id="rd_6m20",
            metric_original="R&D Expenses",
            metric_canonical="research_and_development_expenses",
            value=20.0,
            raw_value="20.0",
            period="6M2020",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "20.0"),
            confidence=0.95,
        ),
        Observation(
            id="rd_6m21",
            metric_original="R&D Expenses",
            metric_canonical="research_and_development_expenses",
            value=32.0,
            raw_value="32.0",
            period="6M2021",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "32.0"),
            confidence=0.95,
        ),
    ]


def _sample_operating_cash_flow_mixed_observations() -> list[Observation]:
    return [
        Observation(
            id="ocf_fy19",
            metric_original="Operating cash flow",
            metric_canonical="operating_cash_flow",
            value=80.0,
            raw_value="80.0",
            period="FY2019",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "80.0"),
            confidence=0.95,
        ),
        Observation(
            id="ocf_fy20",
            metric_original="Operating cash flow",
            metric_canonical="operating_cash_flow",
            value=110.0,
            raw_value="110.0",
            period="FY2020",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=_ev(1, "110.0"),
            confidence=0.95,
        ),
        Observation(
            id="ocf_6m20",
            metric_original="Operating cash flow",
            metric_canonical="operating_cash_flow",
            value=35.0,
            raw_value="35.0",
            period="6M2020",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "35.0"),
            confidence=0.95,
        ),
        Observation(
            id="ocf_6m21",
            metric_original="Operating cash flow",
            metric_canonical="operating_cash_flow",
            value=50.0,
            raw_value="50.0",
            period="6M2021",
            unit="currency",
            currency="RMB",
            period_type="interim_flow",
            evidence=_ev(2, "50.0"),
            confidence=0.95,
        ),
    ]


def test_regression_revenue_series_partitioning() -> None:
    """Requirement 1 & 2: Revenue observations FY2019, FY2020, 6M2020, 6M2021

    QA must partition into compatible series and NEVER compare FY2019 with 6M2021.
    """
    obs = _sample_revenue_mixed_observations()
    series_list = partition_compatible_series(obs, "revenue")

    assert len(series_list) == 2

    # Series 1: FY2019 -> FY2020
    s_fy = next(s for s in series_list if s["period_basis"] == "FY")
    assert s_fy["first"].period == "FY2019"
    assert s_fy["last"].period == "FY2020"
    assert s_fy["val_start"] == 100.0
    assert s_fy["val_end"] == 120.0
    assert s_fy["is_comp"] is True
    assert s_fy["trend_state"] == "INCREASED"

    # Series 2: 6M2020 -> 6M2021
    s_6m = next(s for s in series_list if s["period_basis"] == "6M")
    assert s_6m["first"].period == "6M2020"
    assert s_6m["last"].period == "6M2021"
    assert s_6m["val_start"] == 50.0
    assert s_6m["val_end"] == 65.0
    assert s_6m["is_comp"] is True
    assert s_6m["trend_state"] == "INCREASED"

    # QA must never compare FY2019 with 6M2021
    for s in series_list:
        assert not (s["first"].period == "FY2019" and s["last"].period == "6M2021")


def test_unqualified_claim_auto_repaired_and_export_succeeds() -> None:
    """Requirement 4: If a claim says only 'Revenue increased', auto-repair it to an explicit

    supported period comparison instead of comparing mixed periods and blocking export.
    """
    obs = _sample_revenue_mixed_observations()
    slide = PresentationSlide(
        id="slide_rev",
        slide_type="analysis",
        title="Revenue Trajectory",
        message="Revenue increased during the period.",
        bullets=["Revenue increased significantly."],
        observation_ids=["rev_fy19", "rev_fy20", "rev_6m20", "rev_6m21"],
        source_pages=[1, 2],
    )
    plan = PresentationPlan(title="Revenue Test", slides=[slide])

    # 1. Validation detects unqualified multi-series claim
    validator = ClaimValidator()
    issues = validator.validate_plan(plan, obs)
    assert len(issues) >= 1
    for issue in issues:
        assert issue.is_mixed_period_repair is True
        assert "from FY2019 to FY2020 and from 6M2020 to 6M2021" in issue.supported_period_text

    # 2. Repair rewrites the claim with explicit supported period bounds
    repaired_plan, repairs = repair_presentation_plan(plan, obs)
    assert len(repairs) >= 2
    repaired_slide = repaired_plan.slides[0]
    assert "Revenue increased from FY2019 to FY2020 and from 6M2020 to 6M2021" in repaired_slide.message
    assert "Revenue increased from FY2019 to FY2020 and from 6M2020 to 6M2021" in repaired_slide.bullets[0]

    # 3. Revalidation passes cleanly with Critical QA enabled
    clean_issues = validator.validate_plan(repaired_plan, obs)
    assert len(clean_issues) == 0

    # 4. Full QA pipeline does not block export
    unrepaired_plan = PresentationPlan(
        title="Revenue Test",
        slides=[
            PresentationSlide(
                id="slide_rev",
                slide_type="analysis",
                title="Revenue Trajectory",
                message="Revenue increased during the period.",
                bullets=["Revenue increased significantly."],
                observation_ids=["rev_fy19", "rev_fy20", "rev_6m20", "rev_6m21"],
                source_pages=[1, 2],
            )
        ],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="d1", sha256="1" * 64, safe_filename="doc.pdf", page_count=5),
        profile=DocumentProfile(document_purpose="financial review"),
        observations=obs,
        presentation_plan=unrepaired_plan,
    )
    qa_report = run_comprehensive_qa(result, auto_repair=True)
    assert qa_report.critical_errors == []
    assert any(info.code == "claim_contradiction_repaired" for info in qa_report.info)


def test_contradictory_claim_repaired_with_explicit_periods() -> None:
    """If a claim asserts 'Revenue decreased' when values actually increased in both series,

    it must be detected as contradiction and repaired to 'increased' with explicit periods.
    """
    obs = _sample_revenue_mixed_observations()
    slide = PresentationSlide(
        id="slide_rev_wrong",
        slide_type="analysis",
        title="Revenue Performance",
        message="Revenue decreased unexpectedly.",
        observation_ids=["rev_fy19", "rev_fy20", "rev_6m20", "rev_6m21"],
        source_pages=[1, 2],
    )
    repaired_slide, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) >= 1
    assert "Revenue increased from FY2019 to FY2020 and from 6M2020 to 6M2021" in repaired_slide.message

    validator = ClaimValidator()
    clean_issues = validator.validate_slide(repaired_slide, obs)
    assert len(clean_issues) == 0


def test_explicit_mixed_period_claim_remains_blocked() -> None:
    """Crucial non-negotiable rule: Do NOT weaken the period compatibility blocker.

    If slide text explicitly claims comparison across incompatible periods
    ('Revenue increased from FY2019 to 6M2021'), QA must block export.
    """
    obs = _sample_revenue_mixed_observations()
    slide = PresentationSlide(
        id="slide_bad_cross",
        slide_type="analysis",
        title="Revenue Analysis",
        message="Revenue increased from FY2019 to 6M2021.",
        observation_ids=["rev_fy19", "rev_fy20", "rev_6m20", "rev_6m21"],
        source_pages=[1, 2],
    )
    validator = ClaimValidator()
    issues = validator.validate_slide(slide, obs)

    assert len(issues) == 1
    assert issues[0].expected_direction == "INCOMPATIBLE"
    assert "incompatible periods" in issues[0].message
    assert issues[0].is_mixed_period_repair is False

    # Auto-repair must NOT rewrite this unsafe comparison; export remains blocked
    repaired_slide, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) == 0
    assert repaired_slide.message == "Revenue increased from FY2019 to 6M2021."


def test_adjusted_net_loss_mixed_period_rule() -> None:
    """Requirement 5: Apply the same rule to adjusted net loss and all flow metrics."""
    obs = _sample_loss_mixed_observations()
    series_list = partition_compatible_series(obs, "adjusted_net_loss")

    assert len(series_list) == 2
    s_fy = next(s for s in series_list if s["period_basis"] == "FY")
    assert s_fy["trend_state"] == "LOSS_NARROWED"
    s_6m = next(s for s in series_list if s["period_basis"] == "6M")
    assert s_6m["trend_state"] == "LOSS_NARROWED"

    # Contradiction repair: text claims loss widened, underlying data shows loss narrowed in both FY and 6M
    slide = PresentationSlide(
        id="slide_loss",
        slide_type="analysis",
        title="Adjusted Net Loss Widened",
        message="Adjusted net loss widened during the period.",
        observation_ids=["loss_fy19", "loss_fy20", "loss_6m20", "loss_6m21"],
        source_pages=[1, 2],
    )
    repaired_slide, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) >= 2
    assert "Adjusted Net Loss Narrowed from FY2019 to FY2020 and from 6M2020 to 6M2021" in repaired_slide.title
    assert "Adjusted net loss narrowed from FY2019 to FY2020 and from 6M2020 to 6M2021" in repaired_slide.message

    validator = ClaimValidator()
    clean_issues = validator.validate_slide(repaired_slide, obs)
    assert len(clean_issues) == 0


def test_isolated_incompatible_observations_remain_strictly_blocked() -> None:
    """When only 1 FY and 1 6M observation exist (no comparable series >= 2),

    directional assertions must block export.
    """
    obs = [
        Observation(id="o1", metric_original="Revenue", value=100.0, raw_value="100.0", period="FY2019", currency="RMB", period_type="fiscal_year", evidence=_ev(1), confidence=0.9),
        Observation(id="o2", metric_original="Revenue", value=65.0, raw_value="65.0", period="6M2021", currency="RMB", period_type="interim_flow", evidence=_ev(2), confidence=0.9),
    ]
    slide = PresentationSlide(
        id="slide_single_pair",
        slide_type="analysis",
        title="Revenue Analysis",
        message="Revenue decreased over the period.",
        observation_ids=["o1", "o2"],
        source_pages=[1, 2],
    )
    validator = ClaimValidator()
    issues = validator.validate_slide(slide, obs)

    assert len(issues) == 1
    assert issues[0].expected_direction == "INCOMPATIBLE"
    assert "Incompatible period types" in issues[0].message

    _, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) == 0


def test_score_chartability_rejects_mixed_period_series() -> None:
    """score_chartability must reject any series containing mixed FY and interim flow periods."""
    obs = _sample_revenue_mixed_observations()
    res = score_chartability(obs)
    assert res.is_chartable is False
    assert any("Mixed period bases" in r for r in res.reasons)


def test_chart_planner_isolates_coherent_series() -> None:
    """ChartPlanner must select a coherent series via best_period_series and never mix FY + interim in a chart."""
    obs = _sample_revenue_mixed_observations()
    index = DocumentIndex(obs)

    task = AnalysisTask(
        id="task_rev_trend",
        title="Revenue Trend",
        description="Analyze revenue trend",
        analysis_type="linear_trend",
        tool_name="linear_trend",
        required_metrics=["Revenue"],
        observation_query={"observation_ids": [o.id for o in obs]},
        reason="Multi-period revenue trend",
        expected_output="Deterministic trend slope",
    )
    task_res = AnalysisResult(
        task_id=task.id,
        title=task.title,
        result={"slope": 20.0},
        confidence=0.9,
        evidence=[o.evidence[0] for o in obs],
    )

    planner = ChartPlanner()
    charts = planner.plan([task], [task_res], index)

    assert len(charts) >= 1
    chart = charts[0]
    chart_obs = [index.get(oid) for oid in chart.observation_ids]
    # Verify all observations in the planned chart share the exact same period basis
    assert len({extract_basis(o.period) for o in chart_obs}) == 1


def extract_basis(p: str | None) -> str:
    from adaptive_document_agent.document_model.period_semantic_validator import extract_period_basis
    return extract_period_basis(p)


def test_rd_expenses_mixed_period_rule() -> None:
    """Requirement 6 & 7: R&D expenses (expense flow metric) with mixed periods.

    FY2019 (40.0), FY2020 (55.0), 6M2020 (20.0), 6M2021 (32.0).
    QA must partition into FY and 6M series and never compare FY2019 with 6M2021.
    """
    obs = _sample_rd_expenses_mixed_observations()
    series_list = partition_compatible_series(obs, "research_and_development_expenses")

    assert len(series_list) == 2
    s_fy = next(s for s in series_list if s["period_basis"] == "FY")
    assert s_fy["trend_state"] == "INCREASED"
    s_6m = next(s for s in series_list if s["period_basis"] == "6M")
    assert s_6m["trend_state"] == "INCREASED"

    # 1. Contradictory claim repaired
    slide = PresentationSlide(
        id="slide_rd",
        slide_type="analysis",
        title="R&D Expenses",
        message="R&D expenses decreased during the review period.",
        observation_ids=[o.id for o in obs],
        source_pages=[1, 2],
    )
    repaired_slide, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) >= 1
    assert "increased from FY2019 to FY2020 and from 6M2020 to 6M2021" in repaired_slide.message

    validator = ClaimValidator()
    clean_issues = validator.validate_slide(repaired_slide, obs)
    assert len(clean_issues) == 0

    # 2. Explicit cross-period claim remains strictly blocked
    bad_slide = PresentationSlide(
        id="slide_rd_bad",
        slide_type="analysis",
        title="R&D Expenses",
        message="R&D expenses decreased from FY2019 to 6M2021.",
        observation_ids=[o.id for o in obs],
        source_pages=[1, 2],
    )
    bad_issues = validator.validate_slide(bad_slide, obs)
    assert len(bad_issues) == 1
    assert bad_issues[0].expected_direction == "INCOMPATIBLE"


def test_operating_cash_flow_mixed_period_rule() -> None:
    """Requirement 6 & 7: Operating cash flow (cash flow metric) with mixed periods.

    FY2019 (80.0), FY2020 (110.0), 6M2020 (35.0), 6M2021 (50.0).
    QA must partition into FY and 6M series and never compare FY2019 with 6M2021.
    """
    obs = _sample_operating_cash_flow_mixed_observations()
    series_list = partition_compatible_series(obs, "operating_cash_flow")

    assert len(series_list) == 2
    s_fy = next(s for s in series_list if s["period_basis"] == "FY")
    assert s_fy["trend_state"] == "INCREASED"
    s_6m = next(s for s in series_list if s["period_basis"] == "6M")
    assert s_6m["trend_state"] == "INCREASED"

    slide = PresentationSlide(
        id="slide_ocf",
        slide_type="analysis",
        title="Operating Cash Flow",
        message="Operating cash flow decreased significantly.",
        observation_ids=[o.id for o in obs],
        source_pages=[1, 2],
    )
    repaired_slide, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) >= 1
    assert "increased from FY2019 to FY2020 and from 6M2020 to 6M2021" in repaired_slide.message

    validator = ClaimValidator()
    clean_issues = validator.validate_slide(repaired_slide, obs)
    assert len(clean_issues) == 0

    # Verify comprehensive QA passes with auto-repair
    plan = PresentationPlan(
        title="OCF Test",
        slides=[slide],
    )
    result = PipelineResult(
        document=ParsedDocument(document_id="d_ocf", sha256="2" * 64, safe_filename="ocf.pdf", page_count=5),
        profile=DocumentProfile(document_purpose="cash flow review"),
        observations=obs,
        presentation_plan=plan,
    )
    qa_report = run_comprehensive_qa(result, auto_repair=True)
    assert qa_report.critical_errors == []


def test_qa_error_deduplication_single_issue_per_component() -> None:
    """Requirement 5: Deduplicate QA errors.

    Do not generate multiple critical errors for the same:
    slide + metric + component + incompatible series.
    One root contradiction should produce one structured issue.
    """
    obs = _sample_revenue_mixed_observations()
    slide = PresentationSlide(
        id="slide_multi_clause",
        slide_type="analysis",
        title="Revenue Analysis",
        message="Revenue decreased unexpectedly.",
        # Bullet contains two clauses each asserting decrease for Revenue
        bullets=["Revenue decreased significantly, while also dropping across the period."],
        observation_ids=[o.id for o in obs],
        source_pages=[1, 2],
    )
    validator = ClaimValidator()
    issues = validator.validate_slide(slide, obs)

    # Bullet must generate only ONE issue for the bullet component, not multiple
    bullet_issues = [i for i in issues if i.target_component == "bullet" and i.bullet_index == 0]
    assert len(bullet_issues) == 1


def test_chart_planner_isolates_coherent_series_all_flow_metrics() -> None:
    """Requirement 3 & 6: ChartPlanner isolates coherent series for ALL flow metrics."""
    samples = [
        ("Revenue", _sample_revenue_mixed_observations()),
        ("Adjusted Net Loss", _sample_loss_mixed_observations()),
        ("R&D Expenses", _sample_rd_expenses_mixed_observations()),
        ("Operating cash flow", _sample_operating_cash_flow_mixed_observations()),
    ]

    for metric_name, obs in samples:
        index = DocumentIndex(obs)
        task = AnalysisTask(
            id=f"task_{metric_name.lower().replace(' ', '_')}",
            title=f"{metric_name} Trend",
            description=f"Analyze {metric_name} trend",
            analysis_type="linear_trend",
            tool_name="linear_trend",
            required_metrics=[metric_name],
            observation_query={"observation_ids": [o.id for o in obs]},
            reason=f"Multi-period {metric_name} trend",
            expected_output="Deterministic trend slope",
        )
        task_res = AnalysisResult(
            task_id=task.id,
            title=task.title,
            result={"slope": 10.0},
            confidence=0.9,
            evidence=[o.evidence[0] for o in obs],
        )

        planner = ChartPlanner()
        charts = planner.plan([task], [task_res], index)

        assert len(charts) >= 1, f"Expected chart for {metric_name}"
        for chart in charts:
            chart_obs = [index.get(oid) for oid in chart.observation_ids if index.get(oid)]
            bases = {extract_basis(o.period) for o in chart_obs}
            assert len(bases) == 1, f"Chart for {metric_name} contains mixed period bases: {bases}"

