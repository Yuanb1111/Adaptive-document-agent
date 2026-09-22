"""Regression coverage for failed fallback plans and fragmented amounts."""

import pytest

from adaptive_document_agent.agent.presentation_plan_recovery import PresentationPlanRecovery
from adaptive_document_agent.models import DocumentPage, ValidationIssue
from adaptive_document_agent.ui import technical
from adaptive_document_agent.validation.presentation_plan_validator import PresentationPlanValidator as Validator
from tests.test_pptx_export import _result


@pytest.mark.parametrize(("text", "expected"), [
    ("RMB286.7m", {"286.7"}),
    ("RMB174.3m", {"174.3"}),
    ("USD-286.7 million", {"-286.7"}),
    ("HKD1,234.5; EUR2.4bn", {"1234.5", "2.4"}),
    ("RMB '000; RMB’000; FY2023", {"2023"}),
    ("13.0 % and 3.6%", {"13.0%", "3.6%"}),
    ("SKU286.7 and item174,300", set()),
    ("RMB 286.7 million; 1’234", {"286.7", "1234"}),
])
def test_complete_numeric_tokens(text, expected):
    assert Validator._numbers(text) == expected


def summary_result():
    result = _result()
    result.document.pages = [
        DocumentPage(page_number=1, text="ACME AUTOMATION LIMITED\nGlobal Offering"),
        DocumentPage(page_number=8, text="Company profile and products"),
        DocumentPage(page_number=234, text="Market share 13.0% and 3.6%. Revenue RMB286.7 million."),
    ]
    result.profile.document_summary = "Market share was 13.0% and 3.6%. Revenue was RMB286.7m. (PDF pp. 234–235)"
    result.profile.document_summary_pages = [234, 235]
    return result


def test_fallback_binds_summary_to_summary_pages_and_preserves_raw_result():
    result = summary_result()
    before = result.model_dump()
    plan = PresentationPlanRecovery().fallback(result)
    assert plan.company.name == "ACME AUTOMATION LIMITED"
    assert plan.company.field_source_pages["name"] == [1]
    assert plan.company.field_source_pages["one_line_description"] == [234, 235]
    assert "13.0%" in plan.company.one_line_description
    assert "PDF pp." not in plan.company.one_line_description
    assert {234, 235} <= set(plan.company.source_pages)
    assert plan.planning_origin == "fallback"
    assert result.model_dump() == before
    Validator().validate(plan, result)


@pytest.mark.parametrize("pages", [[], [999]])
def test_fallback_does_not_assign_identity_pages_to_unsourced_summary(pages):
    result = summary_result()
    result.profile.document_summary_pages = pages
    plan = PresentationPlanRecovery().fallback(result)
    assert plan.company.one_line_description == ""
    assert result.profile.document_summary


def test_fallback_omits_whole_unsupported_summary_without_changing_source():
    result = summary_result()
    result.profile.document_summary = "Market share was 99.9%, not 13.0%."
    plan = PresentationPlanRecovery().fallback(result)
    assert plan.company.one_line_description == ""
    assert result.profile.document_summary == "Market share was 99.9%, not 13.0%."


def test_field_citation_cannot_borrow_numbers_from_other_company_fields():
    result = summary_result()
    plan = PresentationPlanRecovery().fallback(result)
    plan.company.field_source_pages["one_line_description"] = [8]
    with pytest.raises(ValueError, match="one_line_description.*unsupported numeric"):
        Validator().validate(plan, result)
    plan.company.field_source_pages["one_line_description"] = [999]
    with pytest.raises(ValueError, match="outside the document"):
        Validator().validate(plan, result)


def test_empty_page_set_does_not_authorize_all_observations():
    assert Validator._allowed_company_numbers(set(), _result()) == set()


def test_all_summary_sources_survive_company_extraction():
    result = summary_result()
    result.profile.document_summary_pages = list(range(230, 250))
    plan = PresentationPlanRecovery().fallback(result)
    assert set(range(230, 250)) <= set(plan.company.source_pages)
    assert plan.company.field_source_pages["one_line_description"] == list(range(230, 250))


def test_old_saved_result_is_not_stamped_as_current_version():
    from adaptive_document_agent.models import PipelineResult
    from adaptive_document_agent.services.export import export_json
    result = _result()
    old_payload = result.model_dump(exclude={"pipeline_version"})
    assert PipelineResult.model_validate(old_payload).pipeline_version is None
    result.pipeline_version = "original-run-version"
    assert PipelineResult.model_validate_json(export_json(result)).pipeline_version == "original-run-version"


def test_unsupported_currency_claim_still_rejected():
    result = summary_result()
    plan = PresentationPlanRecovery().fallback(result)
    plan.slides[2].message = "Revenue was RMB999.7m."
    with pytest.raises(ValueError, match="999.7"):
        Validator().validate(plan, result)


def test_technical_ui_shows_both_failures_and_legacy_status():
    result = _result()
    result.validation_warnings.extend([
        ValidationIssue(code="presentation_plan_failed", message="AI planning failed.", stage="presentation"),
        ValidationIssue(code="presentation_plan_fallback_failed", message="Fallback provenance failed.", stage="presentation"),
    ])
    class UI:
        def __init__(self):
            self.messages = []
        def __getattr__(self, name):
            return lambda value: self.messages.append((name, value))
    ui = UI()
    technical.render(ui, result)
    assert ("error", "Fallback provenance failed.") in ui.messages
    assert any("legacy draft" in str(value) for _, value in ui.messages)
