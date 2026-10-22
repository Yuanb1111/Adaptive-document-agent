"""Export decisions describe final evidence, including late cross-slide repairs."""
from copy import deepcopy

import pytest

from adaptive_document_agent.models import (
    DocumentProfile, ParsedDocument, PipelineResult, PresentationPlan, PresentationSlide,
)
from adaptive_document_agent.services.qa_reporter import run_comprehensive_qa
from adaptive_document_agent.validation.claim_validator import ClaimValidator
from adaptive_document_agent.validation.presentation_evidence_alignment import align_redundant_slide_evidence
from tests.test_presentation_evidence_alignment import _fact


def duplicate_result(contexts=("A", "B", "C")):
    observations = [
        _fact(f"{context}_{year}", year, value, context=context, page=index + 1)
        for index, context in enumerate(contexts)
        for year, value in ((2021, 100), (2022, 120), (2023, 150))
    ]
    ids = [o.id for o in observations]
    slide = PresentationSlide(
        id="summary", slide_type="executive_summary", title="Executive summary",
        bullets=["Inventories increased from 2021-12-31 to 2023-12-31."],
        observation_ids=ids, bullet_observation_ids=[ids],
        source_pages=list(range(1, len(contexts) + 1)),
    )
    return PipelineResult(
        document=ParsedDocument(document_id="test", sha256="1" * 64,
                                safe_filename="test.pdf", page_count=len(contexts)),
        profile=DocumentProfile(), observations=observations,
        presentation_plan=PresentationPlan(title="Inventory", slides=[slide]),
    )


@pytest.mark.parametrize("contexts", [("A", "B", "C"), ("C", "B", "A"),
                                      ("D", "B", "C", "A"), ("E", "D", "C", "B", "A")])
def test_equal_coverage_duplicates_align_in_one_pass(contexts):
    result = duplicate_result(contexts)
    before = deepcopy(result.observations)
    plan = result.presentation_plan
    assert ClaimValidator().validate_plan(plan, result.observations)
    assert align_redundant_slide_evidence(plan, result.observations, [])
    expected = [f"A_{year}" for year in (2021, 2022, 2023)]
    assert plan.slides[0].observation_ids == expected
    assert plan.slides[0].bullet_observation_ids == [expected]
    assert plan.slides[0].source_pages == [contexts.index("A") + 1]
    assert not ClaimValidator().validate_plan(plan, result.observations)
    assert not align_redundant_slide_evidence(plan, result.observations, [])
    assert result.observations == before


def test_first_export_audit_agrees_with_recheck_after_duplicate_repairs():
    result = duplicate_result()
    first = run_comprehensive_qa(result)
    assert not first.is_export_blocked
    assert any(i.code == "claim_contradiction_repaired" for i in first.info)
    snapshot = deepcopy(result)
    checked = run_comprehensive_qa(result, auto_repair=False)
    assert checked.critical_errors == first.critical_errors == []
    assert result == snapshot


@pytest.mark.parametrize("conflict", ["value", "currency", "unit_scale", "audited_status"])
def test_conflicting_duplicate_still_blocks_first_audit_and_recheck(conflict):
    result = duplicate_result()
    setattr(result.observations[-1], conflict, {
        "value": 151000, "currency": "USD", "unit_scale": 1, "audited_status": "unaudited",
    }[conflict])
    before = deepcopy(result.observations)
    for auto in (True, False):
        report = run_comprehensive_qa(result, auto_repair=auto)
        assert report.is_export_blocked
        assert any(i.code == "directional_contradiction" for i in report.critical_errors)
    assert result.observations == before


def test_competing_supersets_are_not_chosen_by_provenance_order():
    result = duplicate_result()
    result.observations.extend([
        _fact("A_extra", 2024, 160, context="A", page=1),
        _fact("B_extra", 2025, 180, context="B", page=2),
    ])
    result.presentation_plan.slides[0].observation_ids.extend(["A_extra", "B_extra"])
    assert not align_redundant_slide_evidence(result.presentation_plan, result.observations, [])


def test_late_source_repair_does_not_leave_an_obsolete_claim_error(monkeypatch):
    # Isolate the actual cross-slide repair from the earlier repair stage.
    # Its final valid references must determine the first returned report.
    from adaptive_document_agent.services import qa_reporter
    monkeypatch.setattr(qa_reporter, "repair_presentation_plan_claims", lambda result: [])
    result = duplicate_result()
    report = run_comprehensive_qa(result)
    assert not report.is_export_blocked
    assert any(i.code == "summary_detail_contradiction_repaired" for i in report.info)
    assert not run_comprehensive_qa(result, auto_repair=False).critical_errors


def test_late_change_cannot_escape_final_claim_validation(monkeypatch):
    from adaptive_document_agent.validation.cross_slide_validator import CrossSlideValidator

    def introduce_contradiction(self, *, auto_repair=True):
        self.plan.slides[0].bullets[0] = "Inventories decreased from 2021-12-31 to 2023-12-31."
        return []

    monkeypatch.setattr(CrossSlideValidator, "validate_and_repair", introduce_contradiction)
    result = duplicate_result(("A",))
    report = run_comprehensive_qa(result)
    assert report.is_export_blocked
    assert any(i.code == "directional_contradiction" for i in report.critical_errors)
