"""Tests for generic slide topic alignment, semantic topic groups, and QA mismatch deduplication.

Verifies:
1. "Revenue Expanded Across the Track Record Period" ↔ Revenue
2. "Net Turned Profitable and Adjusted EBITDA Turned Positive"
   ↔ (Loss)/profit for the year/period
   ↔ Adjusted EBITDA
3. "Operating Expenses Increased as Revenue Scaled"
   ↔ Selling and distribution expenses
   ↔ R&D expenses
   ↔ Administrative expenses
4. Full slide context (title + section_title + message + bullets) used for topic alignment.
5. Positive evidence required for slide_topic_mismatch blocker.
6. Deduplication: One slide + one unrelated metric family = one QA issue.
"""

from __future__ import annotations

from adaptive_document_agent.document_model.topic_matcher import (
    direct_metric_match,
    is_positive_topic_mismatch,
    metrics_match_topic,
)
from adaptive_document_agent.models import (
    ChartPlan,
    CompanyProfile,
    DocumentProfile,
    Observation,
    ParsedDocument,
    PipelineResult,
    PresentationPlan,
    PresentationSlide,
    ReportPlan,
    SourceEvidence,
)
from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa


def _evidence(page: int = 15) -> SourceEvidence:
    return SourceEvidence(page=page, text="100.0", extraction_method="digital_table", confidence=0.95)


def _obs(
    name: str,
    val: float,
    period: str,
    *,
    canonical: str = "",
    page: int = 15,
) -> Observation:
    return Observation(
        id=f"{name.lower().replace(' ', '_').replace('/', '_')}_{period}",
        metric_original=name,
        canonical_name=canonical or name.lower().replace(" ", "_"),
        value=val,
        raw_value=str(val),
        period=period,
        evidence=[_evidence(page)],
        confidence=0.95,
    )


def _build_result(slide: PresentationSlide, observations: list[Observation], charts: list[ChartPlan] | None = None) -> PipelineResult:
    all_charts = charts or []
    plan = PresentationPlan(
        title="Institutional Review",
        company=CompanyProfile(name="Test Issuer", source_pages=[15]),
        slides=[
            PresentationSlide(id="cover", slide_type="cover", title="Cover"),
            PresentationSlide(id="co", slide_type="company_overview", title="Company Overview"),
            PresentationSlide(
                id="exec",
                slide_type="executive_summary",
                title="Executive Summary",
                observation_ids=[observations[0].id] if observations else [],
                source_pages=[15],
            ),
            slide,
            PresentationSlide(id="dq", slide_type="data_quality", title="Data Quality"),
            PresentationSlide(id="app", slide_type="appendix", title="Appendix"),
        ],
    )
    return PipelineResult(
        document=ParsedDocument(document_id="doc1", sha256="hash1", safe_filename="doc.pdf", page_count=50),
        profile=DocumentProfile(document_type="Prospectus", document_summary="Test Prospectus"),
        observations=observations,
        charts=all_charts,
        presentation_plan=plan,
        report_plan=ReportPlan(title="Report"),
    )


# ==============================================================================
# 1. Example 1: Revenue Expanded Across the Track Record Period ↔ Revenue
# ==============================================================================

def test_example_1_revenue_expanded_matches_revenue():
    """'Revenue Expanded Across the Track Record Period' matches Revenue observation."""
    obs_rev = _obs("Revenue", 1200.0, "FY2022", canonical="revenue")

    title = "Revenue Expanded Across the Track Record Period"
    assert metrics_match_topic(obs_rev, "", title) is True

    slide = PresentationSlide(
        id="slide_rev",
        slide_type="analysis",
        title=title,
        message="Top-line growth trajectory was maintained.",
        section_title="Financial Performance",
        observation_ids=[obs_rev.id],
        source_pages=[15],
    )
    assert is_positive_topic_mismatch(obs_rev, slide) is False

    result = _build_result(slide, [obs_rev])
    qa = run_comprehensive_qa(result)

    mismatch_errors = [e for e in qa.critical_errors if e.code == "slide_topic_mismatch"]
    assert not mismatch_errors, f"Unexpected slide_topic_mismatch errors: {mismatch_errors}"


# ==============================================================================
# 2. Example 2: Net Turned Profitable and Adjusted EBITDA Turned Positive
# ==============================================================================

def test_example_2_net_turned_profitable_and_adjusted_ebitda():
    """'Net Turned Profitable and Adjusted EBITDA Turned Positive' matches (Loss)/profit and Adjusted EBITDA."""
    obs_net = _obs("(Loss)/profit for the year/period", 45.0, "FY2023", canonical="net_profit")
    obs_ebitda = _obs("Adjusted EBITDA", 120.0, "FY2023", canonical="ebitda")

    title = "Net Turned Profitable and Adjusted EBITDA Turned Positive"

    # Both must match topic
    assert metrics_match_topic(obs_net, "", title) is True
    assert metrics_match_topic(obs_ebitda, "", title) is True

    slide = PresentationSlide(
        id="slide_prof",
        slide_type="analysis",
        title=title,
        message="Operational turnaround drove positive profitability.",
        section_title="Profitability",
        observation_ids=[obs_net.id, obs_ebitda.id],
        source_pages=[15],
    )

    assert is_positive_topic_mismatch(obs_net, slide) is False
    assert is_positive_topic_mismatch(obs_ebitda, slide) is False

    result = _build_result(slide, [obs_net, obs_ebitda])
    qa = run_comprehensive_qa(result)

    mismatch_errors = [e for e in qa.critical_errors if e.code == "slide_topic_mismatch"]
    assert not mismatch_errors, f"Unexpected slide_topic_mismatch errors: {mismatch_errors}"


# ==============================================================================
# 3. Example 3: Operating Expenses Increased as Revenue Scaled
# ==============================================================================

def test_example_3_operating_expenses_matches_rd_selling_admin():
    """'Operating Expenses Increased as Revenue Scaled' matches Selling, R&D, and Administrative expenses."""
    obs_selling = _obs("Selling and distribution expenses", 150.0, "FY2022", canonical="selling_expenses")
    obs_rd = _obs("R&D expenses", 210.0, "FY2022", canonical="rd_expenses")
    obs_admin = _obs("Administrative expenses", 85.0, "FY2022", canonical="admin_expenses")

    title = "Operating Expenses Increased as Revenue Scaled"

    assert metrics_match_topic(obs_selling, "", title) is True
    assert metrics_match_topic(obs_rd, "", title) is True
    assert metrics_match_topic(obs_admin, "", title) is True

    slide = PresentationSlide(
        id="slide_opex",
        slide_type="analysis",
        title=title,
        message="Investments in marketing and R&D supported top-line expansion.",
        section_title="Operating Costs",
        observation_ids=[obs_selling.id, obs_rd.id, obs_admin.id],
        source_pages=[15],
    )

    assert is_positive_topic_mismatch(obs_selling, slide) is False
    assert is_positive_topic_mismatch(obs_rd, slide) is False
    assert is_positive_topic_mismatch(obs_admin, slide) is False

    result = _build_result(slide, [obs_selling, obs_rd, obs_admin])
    qa = run_comprehensive_qa(result)

    mismatch_errors = [e for e in qa.critical_errors if e.code == "slide_topic_mismatch"]
    assert not mismatch_errors, f"Unexpected slide_topic_mismatch errors: {mismatch_errors}"


# ==============================================================================
# 4. Slide Context (Title + Message + Bullets)
# ==============================================================================

def test_slide_topic_determined_by_title_message_and_bullets():
    """Topic determination checks full slide text (title, message, bullets)."""
    obs_rd = _obs("R&D expenses", 200.0, "FY2022", canonical="rd_expenses")

    # Slide title alone does not name R&D, but message and bullets do
    slide = PresentationSlide(
        id="slide_custom",
        slide_type="analysis",
        title="Commercial Scaling and Investment Priorities",
        message="R&D expenses expanded to accelerate platform deployment.",
        section_title="Strategic Focus",
        observation_ids=[obs_rd.id],
        bullets=["Continuous allocation towards R&D expenses and engineering."],
        source_pages=[15],
    )

    assert is_positive_topic_mismatch(obs_rd, slide) is False

    result = _build_result(slide, [obs_rd])
    qa = run_comprehensive_qa(result)
    mismatch_errors = [e for e in qa.critical_errors if e.code == "slide_topic_mismatch"]
    assert not mismatch_errors


# ==============================================================================
# 5. Positive Evidence Required & Critical Blocker Preserved
# ==============================================================================

def test_positive_evidence_required_and_critical_blocker_preserved():
    """Positive evidence of mismatch must trigger critical blocker, while broad titles do not."""
    obs_rd = _obs("Research and development expenses", 282.0, "FY2020", canonical="rd_expenses")
    obs_gp = _obs("Gross profit", 950.0, "FY2020", canonical="gross_profit")

    # Specific slide: R&D Expense Trajectory
    slide_specific = PresentationSlide(
        id="slide_specific",
        slide_type="analysis",
        title="R&D Expense Trajectory",
        message="R&D expenses increased across the track record period.",
        section_title="Operating Expenses",
        observation_ids=[obs_rd.id, obs_gp.id],  # Gross profit is positively unrelated to R&D!
        source_pages=[15],
    )

    # Gross profit is a positive mismatch against R&D
    assert is_positive_topic_mismatch(obs_gp, slide_specific) is True
    assert is_positive_topic_mismatch(obs_rd, slide_specific) is False

    result_specific = _build_result(slide_specific, [obs_rd, obs_gp])
    qa_specific = run_comprehensive_qa(result_specific)
    assert qa_specific.is_export_blocked is True
    assert any(e.code == "slide_topic_mismatch" for e in qa_specific.critical_errors)

    # Broad slide: Historical Financial Highlights (no mutually exclusive topic)
    slide_broad = PresentationSlide(
        id="slide_broad",
        slide_type="analysis",
        title="Historical Financial Performance Overview",
        message="Summary of key financial statement metrics.",
        section_title="Overview",
        observation_ids=[obs_rd.id, obs_gp.id],
        source_pages=[15],
    )
    # Neither should be flagged as positive mismatch on a broad overview
    assert is_positive_topic_mismatch(obs_rd, slide_broad) is False
    assert is_positive_topic_mismatch(obs_gp, slide_broad) is False


# ==============================================================================
# 6. Deduplication: One Slide + One Unrelated Metric Family = One QA Issue
# ==============================================================================

def test_deduplication_one_issue_per_slide_and_metric_family():
    """Multiple observation periods of an unrelated metric yield exactly ONE slide_topic_mismatch issue."""
    obs_gp1 = _obs("Gross profit", 700.0, "FY2020", canonical="gross_profit")
    obs_gp2 = _obs("Gross profit", 850.0, "FY2021", canonical="gross_profit")
    obs_gp3 = _obs("Gross profit", 1020.0, "FY2022", canonical="gross_profit")
    obs_rd = _obs("Research and development expenses", 282.0, "FY2020", canonical="rd_expenses")

    all_obs = [obs_rd, obs_gp1, obs_gp2, obs_gp3]

    slide = PresentationSlide(
        id="slide_rd_multi",
        slide_type="analysis",
        title="R&D Expense Trajectory",
        message="R&D expenses increased across the period.",
        section_title="R&D",
        observation_ids=[o.id for o in all_obs],
        source_pages=[15],
    )

    result = _build_result(slide, all_obs)
    qa = run_comprehensive_qa(result)

    mismatch_errors = [e for e in qa.critical_errors if e.code == "slide_topic_mismatch"]
    # Must be deduplicated: exactly 1 error for Gross Profit, not 3!
    assert len(mismatch_errors) == 1
    assert set(mismatch_errors[0].related_ids) == {obs_gp1.id, obs_gp2.id, obs_gp3.id}
