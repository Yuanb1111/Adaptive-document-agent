"""Reporting retries reuse only a complete, still-source-bound introduction."""

import pytest

from adaptive_document_agent.agent import company_introduction as introduction, orchestrator
from adaptive_document_agent.agent.compact_summary import generate_compact_summary
from adaptive_document_agent.models import PresentationPlan
from adaptive_document_agent.models.presentation import CompanyProfile
from adaptive_document_agent.services.company_summary import validate_summary
from adaptive_document_agent.services.presentation_requirements import apply_presentation_budget, fixed_presentation_budget
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION
from tests.test_compact_summary_v111 import fixture, Reviewer
from tests.test_early_company_introduction import configure_pipeline
from tests.test_total_file_budget_v130 import choose


def checkpoint():
    result, review, draft = fixture(1)
    result.document.sha256 = review.document_sha256 = sha256_bytes(b"synthetic")
    result.profile.report_requirements = apply_presentation_budget(None, "", fixed_presentation_budget())
    choose(result, review)
    company = generate_compact_summary(Reviewer(draft), result, review,
                                       CompanyProfile(summary_review=review))
    review.status = "complete"
    result.presentation_plan = PresentationPlan(title="Retained deck", company=company)
    result.pipeline_version = PIPELINE_VERSION
    result.pipeline_state, result.retry_from = "partial", "reporting"
    assert not validate_summary(company, result)
    return result


@pytest.mark.parametrize("local", [False, True])
def test_reporting_resume_reuses_complete_introduction_without_requests_or_duplicate_attachment(monkeypatch, local):
    saved = checkpoint()
    before = saved.model_dump_json()
    harness = configure_pipeline(monkeypatch, source=saved, local=local)
    applied = []
    apply = introduction._apply_introduction

    def record(plan, company):
        applied.append(company)
        return apply(plan, company)

    monkeypatch.setattr(introduction, "_apply_introduction", record)
    result = orchestrator.DocumentOrchestrator(harness.gateway).analyse_pdf(b"synthetic", resume=saved)

    assert harness.client.operations == []
    assert len(applied) == 1
    assert result.presentation_plan.company == saved.presentation_plan.company
    assert result.presentation_plan.company is not saved.presentation_plan.company
    assert len(result.presentation_plan.company.summary_pages) == 1
    assert not validate_summary(result.presentation_plan.company, result)
    assert saved.model_dump_json() == before


@pytest.mark.parametrize("mutation", ["copy", "source", "meaning_digest", "incomplete", "missing"])
def test_reporting_resume_regenerates_when_retained_introduction_fails_ordinary_validation(monkeypatch, mutation):
    saved = checkpoint()
    company = saved.presentation_plan.company
    if mutation == "copy":
        company.summary_pages[0].items[0].text += " An unsupported additional claim."
    elif mutation == "source":
        saved.document.pages[0].text = "Different source with no scheduling or training statement."
    elif mutation == "meaning_digest":
        company.summary_review.plan_audits[-1]["required_meanings_digest"] = "tampered"
    elif mutation == "incomplete":
        company.summary_review.status = "incomplete"
    else:
        saved.presentation_plan = None
    assert saved.presentation_plan is None or not introduction._has_valid_introduction(saved.presentation_plan, saved)
    before = saved.model_dump_json()
    harness = configure_pipeline(monkeypatch, source=saved, local=True)
    result = orchestrator.DocumentOrchestrator(harness.gateway).analyse_pdf(b"synthetic", resume=saved)

    # The synthetic regeneration source has no pages 5/18 selected by this mock.
    # Its real request and ordinary failure prove a rejected audit was not reused.
    assert harness.client.operations == ["IntroductionPages"]
    assert result.pipeline_state == "partial"
    assert result.presentation_plan is None or not result.presentation_plan.company.summary_pages
    assert saved.model_dump_json() == before
