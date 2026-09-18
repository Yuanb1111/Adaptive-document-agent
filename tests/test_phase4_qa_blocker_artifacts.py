from __future__ import annotations

import json
from pathlib import Path
import pytest

from adaptive_document_agent.models import (
    ChartPlan,
    CompanyFact,
    CompanyProfile,
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
from adaptive_document_agent.validation.claim_validator import ClaimValidator


def _sample_doc() -> ParsedDocument:
    return ParsedDocument(
        document_id="test-doc",
        sha256="0" * 64,
        safe_filename="test.pdf",
        page_count=20,
    )


def test_claim_validator_detects_directional_contradiction() -> None:
    """Requirement 4: Detect when slide claims metric decreased but underlying facts increased."""
    ev = SourceEvidence(page=5, text="100", extraction_method="digital_table", confidence=0.9)
    obs = [
        Observation(id="rev_22", metric_original="Revenue", value=100.0, raw_value="100", period="FY2022", unit="currency", evidence=[ev], confidence=0.9),
        Observation(id="rev_23", metric_original="Revenue", value=150.0, raw_value="150", period="FY2023", unit="currency", evidence=[ev], confidence=0.9),
    ]

    # Slide claims revenue decreased
    validator = ClaimValidator()
    issues = validator.validate_slide_claims(
        slide_id="slide_rev",
        claim_text="Revenue decreased significantly over the period",
        observations=obs,
    )

    assert len(issues) == 1
    assert issues[0].code == "directional_contradiction"
    assert "increased from 100.0 to 150.0" in issues[0].message


def test_company_identity_contradiction_resolution() -> None:
    """Requirement 5: Suppress 'unnamed issuer' notes when company identity is resolved."""
    ev = SourceEvidence(page=1, text="Alpha", extraction_method="digital_table", confidence=0.9)
    plan = PresentationPlan(
        title="Analysis",
        company=CompanyProfile(
            name="Alpha Corp",
            identity_state="RESOLVED",
            one_line_description="Leading provider (prospectus for an unnamed issuer).",
            source_pages=[1],
        ),
        slides=[
            PresentationSlide(
                id="quality",
                slide_type="data_quality",
                title="Data Quality",
                bullets=["Extraction note for unnamed issuer", "High confidence OCR on page 1"],
                source_pages=[1],
            )
        ],
    )
    result = PipelineResult(
        document=_sample_doc(),
        profile=DocumentProfile(overview_title="Alpha Corp"),
        presentation_plan=plan,
    )

    qa = run_comprehensive_qa(result)

    # Contradiction should be cleanly resolved and reported in info
    assert any(i.code == "company_identity_reconciled" for i in qa.info)
    assert "unnamed issuer" not in result.presentation_plan.company.one_line_description
    assert not any("unnamed issuer" in b for b in result.presentation_plan.slides[0].bullets)


def test_generate_artifacts_creates_all_4_json_files(tmp_path: Path) -> None:
    """Requirement 12: Output extracted_facts.json, normalized_facts.json, slide_plan.json, qa_report.json."""
    ev = SourceEvidence(page=10, text="500", extraction_method="digital_table", confidence=0.95)
    obs = [
        Observation(id="o1", metric_original="Net Profit", value=500.0, raw_value="500", period="FY2023", unit="currency", evidence=[ev], confidence=0.95),
    ]
    plan = PresentationPlan(
        title="Report",
        slides=[PresentationSlide(id="cov", slide_type="cover", title="Cover")],
    )
    result = PipelineResult(
        document=_sample_doc(),
        profile=DocumentProfile(overview_title="Test Corp"),
        observations=obs,
        presentation_plan=plan,
    )

    files = generate_artifacts(result, tmp_path)

    assert files["extracted_facts"].exists()
    assert files["normalized_facts"].exists()
    assert files["slide_plan"].exists()
    assert files["qa_report"].exists()

    with open(files["qa_report"], encoding="utf-8") as f:
        data = json.load(f)
        assert data["document_title"] == "Test Corp"
        assert data["total_extracted_facts"] == 1


def test_export_blocker_blocks_on_critical_error_and_allows_force() -> None:
    """Export Blocker: Normal PPT export must block on critical error, permit override with force=True."""
    ev = SourceEvidence(page=10, text="-92237", extraction_method="digital_table", confidence=0.95)
    # Simulate double-scaling error: raw is 92237, unit_scale is 1000, value is scaled by 1,000,000 (1000x error)
    bad_obs = Observation(
        id="bad_1",
        metric_original="R&D Expenses",
        value=-92237000000.0,
        raw_value="-92237",
        unit_scale=1000.0,
        period="FY2023",
        unit="currency",
        evidence=[ev],
        confidence=0.95,
    )
    result = PipelineResult(
        document=_sample_doc(),
        profile=DocumentProfile(overview_title="Test"),
        observations=[bad_obs],
        presentation_plan=PresentationPlan(
            title="Deck",
            slides=[PresentationSlide(id="cov", slide_type="cover", title="Cover")],
        ),
    )

    # Normal export must raise CriticalQAError
    with pytest.raises(CriticalQAError) as exc_info:
        export_pptx(result, force=False)
    assert "1000x magnitude error" in str(exc_info.value)

    # Force export should bypass the QA blocker (even if PresentationPlanValidator later validates structure)
    try:
        export_pptx(result, force=True)
    except CriticalQAError:
        pytest.fail("force=True should bypass CriticalQAError")
    except Exception:
        # Downstream plan validator may raise, which is expected for minimal test result
        pass
