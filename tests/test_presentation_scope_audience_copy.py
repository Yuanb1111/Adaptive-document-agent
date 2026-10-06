"""Coverage pages explain omissions while the complete audit stays unchanged."""

import json

import pytest

from adaptive_document_agent.models import PresentationPlan, PresentationTheme, ValidationIssue
from adaptive_document_agent.services.presentation_scope import scope_items, scope_audit_notes
from tests.test_presentation_key_figures import _result


@pytest.mark.parametrize("title", ["Regional profitability", "Production capacity", "Customer satisfaction"])
def test_omitted_topic_keeps_subject_without_exposing_internal_validation_error(title):
    result = _result()
    result.presentation_plan = PresentationPlan(title="Review")
    diagnostic = json.dumps({
        "phase": "initial", "topic": {"id": "topic_private_id", "title": title},
        "error": "Topic topic_private_id contains unsupported numeric claims: ['998877']",
    })
    result.validation_warnings.append(ValidationIssue(
        code="presentation_topic_validation", stage="presentation", message=diagnostic,
    ))
    before = result.model_dump()

    items = scope_items(result)

    omitted = next(item for item in items if item.title == "Not covered: " + title)
    assert "source evidence" in omitted.text
    visible = "\n".join(item.title + "\n" + item.text for item in items)
    assert "topic_private_id" not in visible
    assert "998877" not in visible
    assert "unsupported numeric claims" not in visible
    assert "diagnostics" not in visible and "JSON" not in visible
    assert result.model_dump() == before
    assert result.validation_warnings[-1].message == diagnostic


def test_restored_topic_does_not_keep_an_omission_notice():
    result = _result()
    result.presentation_plan = PresentationPlan(title="Review", themes=[PresentationTheme(
        id="restored", title="Service availability", question="What changed?", rationale="Source series",
    )])
    result.validation_warnings.append(ValidationIssue(
        code="presentation_topic_validation", stage="presentation", message=json.dumps({
            "phase": "initial", "topic": {"id": "restored", "title": "Service availability"},
            "error": "Original draft failed validation.",
        }),
    ))
    assert not any(item.title.startswith("Not covered:") for item in scope_items(result))


@pytest.mark.parametrize("code", [
    "presentation_closing_claim_withheld", "presentation_topic_claims_withheld",
    "presentation_topic_claim_withheld",
])
def test_rejected_draft_claims_stay_in_audit_without_creating_generic_scope_page(code):
    result = _result()
    baseline = scope_items(result)
    diagnostic = "A draft statement was rejected; selected source observations remain unchanged."
    result.validation_warnings.append(ValidationIssue(code=code, stage="presentation", message=diagnostic))
    before = result.model_dump()

    assert scope_items(result) == baseline
    audit = json.loads(scope_audit_notes(result))
    assert any(issue["code"] == code and issue["message"] == diagnostic for issue in audit["validation_warnings"])
    assert result.model_dump() == before


def test_audit_only_claim_rejections_do_not_hide_real_source_limits_or_conflicts():
    result = _result()
    source_limit = "Supplier-level breakdown is not shown."
    source_caveat = "The disclosed bridge excludes estimated amounts."
    result.presentation_plan.coverage_notes = [source_limit]
    result.presentation_plan.themes = [PresentationTheme(
        id="bridge", title="Source bridge", question="Which amounts reconcile?",
        rationale="Reported reconciliation", caveats=[source_caveat], source_pages=[4])]
    result.validation_warnings.extend([
        ValidationIssue(code="presentation_topic_claims_withheld", stage="presentation", message="Draft takeaway rejected."),
        ValidationIssue(code="conflicting_values", stage="validation", message="Two reported amounts disagree."),
    ])
    before = result.model_dump()

    items = scope_items(result)

    assert source_limit in [item.text for item in items]
    assert source_caveat in [item.text for item in items]
    assert any(item.title == "Source validation limit" for item in items)
    assert not any(item.title == "Interpretation limit" for item in items)
    assert result.model_dump() == before
