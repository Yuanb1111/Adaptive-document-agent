from __future__ import annotations

import json
from pathlib import Path
import pytest

from adaptive_document_agent.models import (
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    SourceEvidence,
)
from adaptive_document_agent.services.export import export_pptx
from adaptive_document_agent.services.qa_reporter import (
    CriticalQAError,
    generate_artifacts,
    run_comprehensive_qa,
)
from adaptive_document_agent.validation.claim_validator import (
    ClaimValidator,
    are_observations_compatible,
    repair_presentation_plan,
    repair_slide_claims,
)


def _sample_doc() -> ParsedDocument:
    return ParsedDocument(
        document_id="test-doc-repair",
        sha256="1" * 64,
        safe_filename="test_repair.pdf",
        page_count=10,
    )


def test_loss_narrowed_auto_repair() -> None:
    """Issue 1: Executive Summary says loss 'widened', but values moved from -562.82 to -243.648.

    Loss moved closer to zero -> loss narrowed.
    Claim validator must detect contradiction, and repair loop must rewrite 'widened' -> 'narrowed'.
    """
    ev = SourceEvidence(page=3, text="-562.82", extraction_method="digital_table", confidence=0.95)
    obs = [
        Observation(
            id="loss_22",
            metric_original="Net loss",
            metric_canonical="net_loss",
            value=-562.82,
            raw_value="-562.82",
            period="FY2022",
            unit="currency",
            currency="CNY",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.95,
        ),
        Observation(
            id="loss_23",
            metric_original="Net loss",
            metric_canonical="net_loss",
            value=-243.648,
            raw_value="-243.648",
            period="FY2023",
            unit="currency",
            currency="CNY",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.95,
        ),
    ]

    slide = PresentationSlide(
        id="slide_exec",
        slide_type="executive_summary",
        title="Executive Summary: Net Loss Widened",
        message="Net loss widened from RMB -562.82m to RMB -243.65m during the period.",
        bullets=["Net loss widened compared to the prior fiscal year."],
        observation_ids=["loss_22", "loss_23"],
        source_pages=[3],
    )

    # 1. Validation detects contradiction before repair
    validator = ClaimValidator()
    issues = validator.validate_slide_claims("slide_exec", " ".join([slide.title, slide.message, *slide.bullets]), obs)
    assert len(issues) >= 1
    assert issues[0].code == "directional_contradiction"
    assert "narrowed from -562.82 to -243.648" in issues[0].message

    # 2. Repair rewrites title, message, and bullets with casing preserved
    repaired_slide, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) >= 3
    assert "Net Loss Narrowed" in repaired_slide.title
    assert "Net loss narrowed from RMB -562.82m" in repaired_slide.message
    assert "Net loss narrowed compared" in repaired_slide.bullets[0]

    # 3. Revalidation passes cleanly
    revalidated_issues = validator.validate_slide_claims("slide_exec", " ".join([repaired_slide.title, repaired_slide.message, *repaired_slide.bullets]), obs)
    assert len(revalidated_issues) == 0


def test_cost_structure_expenses_increase_auto_repair() -> None:
    """Issues 2 & 3:

    - Depreciation and amortization values increased from 4.6 to 5.8 (text said 'declined').
    - Employee benefit expenses values increased from 2.8 to 22.1 (text said 'declined').
    Repair loop must rewrite 'declined' -> 'increased'.
    """
    ev = SourceEvidence(page=5, text="table", extraction_method="digital_table", confidence=0.9)
    obs = [
        Observation(
            id="dep_22",
            metric_original="Depreciation and amortization",
            metric_canonical="depreciation_and_amortization",
            value=4.6,
            raw_value="4.6",
            period="FY2022",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.9,
        ),
        Observation(
            id="dep_23",
            metric_original="Depreciation and amortization",
            metric_canonical="depreciation_and_amortization",
            value=5.8,
            raw_value="5.8",
            period="FY2023",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.9,
        ),
        Observation(
            id="emp_22",
            metric_original="Employee benefit expenses",
            metric_canonical="employee_benefit_expenses",
            value=2.8,
            raw_value="2.8",
            period="FY2022",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.9,
        ),
        Observation(
            id="emp_23",
            metric_original="Employee benefit expenses",
            metric_canonical="employee_benefit_expenses",
            value=22.1,
            raw_value="22.1",
            period="FY2023",
            unit="currency",
            currency="RMB",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.9,
        ),
    ]

    slide = PresentationSlide(
        id="slide_cost",
        slide_type="analysis",
        title="Cost Structure Analysis",
        message="Operating expenses varied across cost centers.",
        bullets=[
            "Depreciation and amortization declined from RMB 4.6m to RMB 5.8m.",
            "Employee benefit expenses declined from RMB 2.8m to RMB 22.1m.",
        ],
        observation_ids=["dep_22", "dep_23", "emp_22", "emp_23"],
        source_pages=[5],
    )

    repaired_slide, repairs = repair_slide_claims(slide, obs)
    assert len(repairs) == 2
    assert "Depreciation and amortization increased from RMB 4.6m to RMB 5.8m." in repaired_slide.bullets[0]
    assert "Employee benefit expenses increased from RMB 2.8m to RMB 22.1m." in repaired_slide.bullets[1]


def test_incompatible_observations_block_auto_repair() -> None:
    """Requirement 4 & 6: Incompatible observations must not be auto-repaired and must block export.

    Testing:
    1. Currency mismatch (CNY vs USD)
    2. Period type mismatch (balance_sheet_date vs fiscal_year)
    3. Reporting basis mismatch (consolidated vs standalone)
    """
    ev = SourceEvidence(page=2, text="val", extraction_method="digital_table", confidence=0.9)

    # 1. Currency mismatch
    obs_cny = Observation(id="o1", metric_original="Revenue", value=100.0, raw_value="100", period="FY2022", currency="CNY", period_type="fiscal_year", evidence=[ev], confidence=0.9)
    obs_usd = Observation(id="o2", metric_original="Revenue", value=150.0, raw_value="150", period="FY2023", currency="USD", period_type="fiscal_year", evidence=[ev], confidence=0.9)
    comp, reason = are_observations_compatible(obs_cny, obs_usd)
    assert not comp
    assert "Currency mismatch" in reason

    # 2. Period type mismatch
    obs_bs = Observation(id="o3", metric_original="Cash", value=50.0, raw_value="50", period="31 Dec 2022", currency="CNY", period_type="balance_sheet_date", evidence=[ev], confidence=0.9)
    obs_fy = Observation(id="o4", metric_original="Cash", value=80.0, raw_value="80", period="FY2023", currency="CNY", period_type="fiscal_year", evidence=[ev], confidence=0.9)
    comp2, reason2 = are_observations_compatible(obs_bs, obs_fy)
    assert not comp2
    assert "Incompatible period types" in reason2

    # 3. Reporting basis mismatch
    obs_cons = Observation(id="o5", metric_original="EBITDA", value=10.0, raw_value="10", period="FY2022", currency="CNY", period_type="fiscal_year", dimensions={"basis": "consolidated"}, evidence=[ev], confidence=0.9)
    obs_stand = Observation(id="o6", metric_original="EBITDA", value=20.0, raw_value="20", period="FY2023", currency="CNY", period_type="fiscal_year", dimensions={"basis": "standalone"}, evidence=[ev], confidence=0.9)
    comp3, reason3 = are_observations_compatible(obs_cons, obs_stand)
    assert not comp3
    assert "Incompatible reporting basis" in reason3

    # Ensure claim validator on incompatible observations keeps export blocked and explains why
    slide = PresentationSlide(
        id="slide_incomp",
        slide_type="analysis",
        title="Revenue Analysis",
        message="Revenue decreased unexpectedly.",
        observation_ids=["o1", "o2"],
        source_pages=[2],
    )
    plan = PresentationPlan(title="Incompatible Test", slides=[slide])
    validator = ClaimValidator()
    issues = validator.validate_plan(plan, [obs_cny, obs_usd])
    assert len(issues) == 1
    assert issues[0].code == "directional_contradiction"
    assert "incompatible" in issues[0].message
    assert "Currency mismatch" in issues[0].message

    # Auto-repair must NOT rewrite incompatible observations
    _, repairs = repair_slide_claims(slide, [obs_cny, obs_usd])
    assert len(repairs) == 0
    assert slide.message == "Revenue decreased unexpectedly."


def test_full_pipeline_qa_repair_and_export_loop() -> None:
    """Requirement 1: Presentation Plan -> Claim Validation -> Repair contradictory wording -> Revalidate -> Export only if valid."""
    ev = SourceEvidence(page=1, text="100", extraction_method="digital_table", confidence=0.95)
    obs = [
        Observation(
            id="rev_22",
            metric_original="Revenue",
            metric_canonical="revenue",
            value=100.0,
            raw_value="100",
            period="FY2022",
            currency="CNY",
            unit="currency",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.95,
        ),
        Observation(
            id="rev_23",
            metric_original="Revenue",
            metric_canonical="revenue",
            value=150.0,
            raw_value="150",
            period="FY2023",
            currency="CNY",
            unit="currency",
            period_type="fiscal_year",
            evidence=[ev],
            confidence=0.95,
        ),
    ]

    # Slide incorrectly claims revenue declined
    slide = PresentationSlide(
        id="slide_rev",
        slide_type="analysis",
        title="Revenue Performance: Revenue Declined",
        section_title="Revenue",
        message="Revenue declined from RMB 100m to RMB 150m during the year.",
        bullets=["Revenue declined across key markets."],
        observation_ids=["rev_22", "rev_23"],
        source_pages=[1],
    )
    plan = PresentationPlan(
        title="Annual Report Deck",
        slides=[
            PresentationSlide(id="cov", slide_type="cover", title="Cover"),
            PresentationSlide(id="ovw", slide_type="company_overview", title="Company Overview", source_pages=[1]),
            PresentationSlide(id="exec", slide_type="executive_summary", title="Executive Summary", message="Overview summary.", source_pages=[1]),
            slide,
            PresentationSlide(id="dq", slide_type="data_quality", title="Data Quality", source_pages=[1]),
            PresentationSlide(id="appx", slide_type="appendix", title="Appendix"),
        ],
    )
    result = PipelineResult(
        document=_sample_doc(),
        profile=DocumentProfile(overview_title="Demo Corp"),
        observations=obs,
        presentation_plan=plan,
    )

    # 1. run_comprehensive_qa with auto_repair=True repairs the plan and passes
    qa = run_comprehensive_qa(result, auto_repair=True)
    assert not qa.has_critical_errors
    assert any(item.code == "claim_contradiction_repaired" for item in qa.info)

    # Slide text should be repaired in place
    assert "Revenue increased from RMB 100m to RMB 150m" in result.presentation_plan.slides[3].message
    assert "Revenue increased across key markets." in result.presentation_plan.slides[3].bullets[0]

    # 2. Export succeeds without throwing CriticalQAError
    pptx_bytes = export_pptx(result, force=False)
    assert len(pptx_bytes) > 0


def test_export_remains_blocked_if_unrepairable_critical_issue_persists() -> None:
    """Export must stay blocked if a critical error (e.g. 1000x magnitude error) cannot be repaired."""
    ev = SourceEvidence(page=1, text="100", extraction_method="digital_table", confidence=0.95)
    bad_obs = Observation(
        id="bad_obs",
        metric_original="R&D Expenses",
        value=-100000000.0,
        raw_value="-100",
        unit_scale=1000.0,  # 1000x scale error
        period="FY2023",
        unit="currency",
        evidence=[ev],
        confidence=0.95,
    )
    result = PipelineResult(
        document=_sample_doc(),
        profile=DocumentProfile(overview_title="Error Corp"),
        observations=[bad_obs],
        presentation_plan=PresentationPlan(
            title="Deck",
            slides=[PresentationSlide(id="cov", slide_type="cover", title="Cover")],
        ),
    )

    with pytest.raises(CriticalQAError) as exc_info:
        export_pptx(result, force=False)
    assert "1000x magnitude error" in str(exc_info.value)


def test_generate_artifacts_reflects_repaired_claims(tmp_path: Path) -> None:
    """Artifacts output: slide_plan.json has repaired text and qa_report.json logs repaired claims."""
    ev = SourceEvidence(page=1, text="50", extraction_method="digital_table", confidence=0.95)
    obs = [
        Observation(id="c1", metric_original="Cost of Sales", value=50.0, raw_value="50", period="FY2022", unit="currency", evidence=[ev], confidence=0.95),
        Observation(id="c2", metric_original="Cost of Sales", value=75.0, raw_value="75", period="FY2023", unit="currency", evidence=[ev], confidence=0.95),
    ]
    slide = PresentationSlide(
        id="cost_slide",
        slide_type="analysis",
        title="Cost Trends",
        section_title="Costs",
        message="Cost of Sales declined from 50 to 75.",
        bullets=["Cost of Sales declined."],
        observation_ids=["c1", "c2"],
        source_pages=[1],
    )
    plan = PresentationPlan(
        title="Cost Report",
        slides=[
            PresentationSlide(id="cov", slide_type="cover", title="Cover"),
            PresentationSlide(id="ovw", slide_type="company_overview", title="Overview", source_pages=[1]),
            PresentationSlide(id="exec", slide_type="executive_summary", title="Exec Summary", message="Summary message.", source_pages=[1]),
            slide,
            PresentationSlide(id="dq", slide_type="data_quality", title="Quality", source_pages=[1]),
            PresentationSlide(id="appx", slide_type="appendix", title="Appendix"),
        ],
    )
    result = PipelineResult(
        document=_sample_doc(),
        profile=DocumentProfile(overview_title="Cost Corp"),
        observations=obs,
        presentation_plan=plan,
    )

    artifacts = generate_artifacts(result, tmp_path)
    assert artifacts["slide_plan"].exists()
    assert artifacts["qa_report"].exists()

    with open(artifacts["slide_plan"], encoding="utf-8") as f:
        slide_data = json.load(f)
        repaired_slide_dict = next(s for s in slide_data["slides"] if s["id"] == "cost_slide")
        assert "Cost of Sales increased from 50 to 75." in repaired_slide_dict["message"]

    with open(artifacts["qa_report"], encoding="utf-8") as f:
        qa_data = json.load(f)
        assert qa_data["is_export_blocked"] is False
        assert any(item["code"] == "claim_contradiction_repaired" for item in qa_data["info"])
