import hashlib
import json

import pytest

from scripts.business_acceptance_report import (
    assess_review, checked_baseline, csv_text, reviewed_artifacts_match, write_report,
)


def facts():
    return [{"fact_id": "revenue", "material": True}, {"fact_id": "condition", "material": True}]


def completed_review():
    return {
        "source_review_complete": True, "output_claim_review_complete": True,
        "additional_claim_errors": 0,
        "facts": [{"fact_id": fact["fact_id"], "status": "represented", "output_locators": ["slide 3"],
                   "checks": {dim: {"correct": 1, "checked": 1}
                              for dim in ("number", "unit", "period", "direction", "support")}}
                  for fact in facts()],
    }


def test_no_outputs_does_not_mean_perfect_accuracy():
    result = assess_review(facts(), {}, run_verified=False)
    assert result["fact_gate"] == "pending"
    assert result["accuracy"]["number"] == {"correct": 0, "checked": 0}
    assert result["unchecked_items"] == 2
    assert result["human_editing_minutes"] is None


def test_generation_success_cannot_replace_source_and_output_review():
    review = completed_review()
    review["source_review_complete"] = False
    assert assess_review(facts(), review, run_verified=True)["fact_gate"] == "pending"
    review["source_review_complete"] = True
    assert assess_review(facts(), review, run_verified=False)["fact_gate"] == "pending"
    assert assess_review(facts(), review, run_verified=True)["fact_gate"] == "passed"


def test_error_remains_in_accuracy_denominator():
    review = completed_review()
    review["facts"][0]["checks"]["period"]["correct"] = 0
    result = assess_review(facts(), review, run_verified=True)
    assert result["fact_gate"] == "failed"
    assert result["accuracy"]["period"] == {"correct": 1, "checked": 2}


def test_additional_output_error_also_enters_accuracy_denominator():
    review = completed_review()
    extra = {"fact_id": "additional-unit", "status": "incorrect", "source_pages": [5],
             "output_locators": ["slide 7"], "checks": {
                 dim: {"correct": 1, "checked": 1}
                 for dim in ("number", "unit", "period", "direction", "support")}}
    extra["checks"]["unit"]["correct"] = 0
    review.update(additional_claims=[extra], additional_claim_errors=1)
    result = assess_review(facts(), review, run_verified=True)
    assert result["fact_gate"] == "failed"
    assert result["accuracy"]["unit"] == {"correct": 2, "checked": 3}
    assert result["detected_errors"] == 1
    review["additional_claim_errors"] = 0
    with pytest.raises(ValueError, match="does not match"):
        assess_review(facts(), review, run_verified=True)


def test_material_omission_cannot_pass_by_writing_less():
    review = completed_review()
    review["facts"][1] = {"fact_id": "condition", "status": "omitted",
        "missing_content": "Scenario assumes a fixed price", "decision_impact": "Runway is conditional"}
    result = assess_review(facts(), review, run_verified=True)
    assert result["fact_gate"] == "failed" and result["undisclosed_material_omissions"] == 1


def test_wrong_fact_with_missing_qualification_counts_both_failures():
    review = completed_review()
    row = review["facts"][0]
    row.update(status="incorrect", missing_content="Owner versus total profit distinction missing",
               decision_impact="Cannot identify profit attributable to shareholders")
    row["checks"]["unit"]["correct"] = 0
    result = assess_review(facts(), review, run_verified=True)
    assert result["detected_errors"] == 1
    assert result["undisclosed_material_omissions"] == 1
    row["status"] = "represented"
    with pytest.raises(ValueError, match="missing component"):
        assess_review(facts(), review, run_verified=True)


def test_specific_output_disclosure_differs_from_generic_disclaimer():
    review = completed_review()
    row = review["facts"][1]
    row.update(status="disclosed", missing_content="Price assumption not established",
               decision_impact="Runway may differ", output_locators=["slide 8 warning"])
    result = assess_review(facts(), review, run_verified=True)
    assert result["specifically_disclosed_material_omissions"] == 1
    assert result["fact_gate"] == "passed"
    row["decision_impact"] = ""
    with pytest.raises(ValueError, match="decision impact"):
        assess_review(facts(), review, run_verified=True)


def test_unknown_and_duplicate_reviews_cannot_inflate_coverage():
    review = completed_review()
    review["facts"].append(review["facts"][0])
    with pytest.raises(ValueError, match="Duplicate or unknown"):
        assess_review(facts(), review, run_verified=True)
    review["facts"] = [{"fact_id": "not_in_source"}]
    with pytest.raises(ValueError, match="Duplicate or unknown"):
        assess_review(facts(), review, run_verified=True)


@pytest.mark.parametrize("counts", [{"correct": 2, "checked": 1}, {"correct": -1, "checked": 1},
                                    {"correct": True, "checked": 1}])
def test_invalid_accuracy_counts_rejected(counts):
    review = completed_review()
    review["facts"][0]["checks"]["number"] = counts
    with pytest.raises(ValueError, match="Invalid accuracy"):
        assess_review(facts(), review, run_verified=True)


def test_unreviewed_additional_output_claims_and_missing_dimensions_stay_pending():
    review = completed_review()
    review["additional_claim_errors"] = None
    assert assess_review(facts(), review, run_verified=True)["fact_gate"] == "pending"
    review["additional_claim_errors"] = 0
    for row in review["facts"]:
        row["checks"]["support"] = {"correct": 0, "checked": 0}
    assert assess_review(facts(), review, run_verified=True)["fact_gate"] == "pending"


def test_one_bad_fact_is_not_counted_as_several_independent_errors():
    review = completed_review()
    row = review["facts"][0]
    row["status"] = "incorrect"
    row["checks"]["period"]["correct"] = 0
    row["checks"]["number"]["correct"] = 0
    result = assess_review(facts(), review, run_verified=True)
    assert result["detected_errors"] == 1
    assert result["failed_accuracy_checks"] == 2


@pytest.mark.parametrize("minutes", [float("nan"), float("inf"), -1, True])
def test_unmeasured_or_invalid_editing_time_cannot_be_fabricated(minutes):
    review = completed_review()
    review["human_editing_minutes"] = minutes
    with pytest.raises(ValueError, match="Editing time"):
        assess_review(facts(), review, run_verified=True)


def test_locked_source_and_checklist_are_both_verified(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"locked source bytes")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    checklist = tmp_path / "checklist.json"
    checklist.write_text(json.dumps({"source_sha256": source_sha, "facts": facts()}), encoding="utf-8")
    sample = {"source_path": str(source), "source_sha256": source_sha,
              "checklist_path": str(checklist), "checklist_sha256": hashlib.sha256(checklist.read_bytes()).hexdigest()}
    assert checked_baseline(sample)["facts"] == facts()
    source.write_bytes(b"other source")
    with pytest.raises(ValueError, match="Source PDF has changed"):
        checked_baseline(sample)
    source.write_bytes(b"locked source bytes")
    checklist.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checklist has changed"):
        checked_baseline(sample)


def test_review_is_bound_to_exact_json_and_ppt_bytes(tmp_path):
    reviewed = {}
    for filename in ("analysis.json", "presentation.pptx"):
        path = tmp_path / filename
        path.write_bytes(filename.encode())
        reviewed[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    review = {"reviewed_artifacts": reviewed}
    assert reviewed_artifacts_match(tmp_path, review)
    (tmp_path / "analysis.json").write_bytes(b"updated analysis")
    assert not reviewed_artifacts_match(tmp_path, review)
    assert not reviewed_artifacts_match(tmp_path, {})


@pytest.mark.parametrize("text", ["=HYPERLINK(\"evil\")", "  +1+2", "@SUM(1)", "\tformula"])
def test_source_checklist_csv_keeps_document_text_inert(text):
    assert csv_text(text) == "'" + text


def test_report_uses_actual_cohort_and_escapes_source_content(tmp_path):
    report = {"acceptance_passed": False, "status": "running", "code_version": "fixed",
              "generation_attempt": 1, "model_settings": {"model": "test-model"}, "samples": [{
                  "sample_id": "sample", "name": "<script>alert(1)</script>", "industry": "test",
                  "official_url": "javascript:alert(1)", "page_count": 10, "source_sha256": "hash",
                  "run_status": "not_started", "review": assess_review(facts(), {}, run_verified=False),
                  "facts": [{"fact_id": "one", "pages": [2], "expected": "=HYPERLINK(\"evil\")",
                             "omission_impact": "<img src=x onerror=alert(1)>", "output_review": {}}]}]}
    write_report(report, tmp_path)
    rendered = (tmp_path / "business-acceptance.html").read_text(encoding="utf-8")
    assert "1份原文及1项" in rendered
    assert "test-model" in rendered and "deepseek-flash" not in rendered
    assert "<script>" not in rendered and "javascript:" not in rendered
    assert "&lt;img" in rendered
    assert "'=HYPERLINK" in (tmp_path / "source-checklist.csv").read_text(encoding="utf-8-sig")
