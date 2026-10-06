"""A rejected introduction item cannot erase independently sourced material."""

from adaptive_document_agent.agent.company_introduction import ensure_company_introduction, prepare_company_introduction
from adaptive_document_agent.models import PresentationPlan
from adaptive_document_agent.services.company_summary import validate_summary
from tests.test_executive_brief import gateway
from tests.test_early_company_introduction import source_only


def test_verified_overview_survives_invalid_business_after_one_repair():
    source, company = source_only()
    good = company.summary_overview.model_dump()
    bad = company.summary_business.model_dump()
    for item in bad["items"]:
        item["source_quote"] = "An invented quotation that the document never contains."
    draft = {"overview": good, "business": bad}
    provider, client = gateway([{"pages": [5, 18]}, draft, draft])
    plan = PresentationPlan(title="Document review")
    with prepare_company_introduction(provider, source) as attach:
        attach(plan)
    assert plan.company.summary_overview == company.summary_overview
    assert plan.company.summary_business is None
    assert not validate_summary(plan.company, source)
    assert any(issue.code == "company_introduction_partial" for issue in source.validation_warnings)
    assert any(issue.code == "company_introduction_repair_audit" for issue in source.validation_warnings)
    assert len(client.calls) == 3


def test_partial_page_keeps_only_verified_items_and_reuses_it_without_new_call():
    source, company = source_only()
    business = company.summary_business.model_dump()
    original = business["items"][0].copy()
    business["items"].append({**original, "text": "Unsupported additional product.", "source_quote": "Absent quotation."})
    draft = {"overview": company.summary_overview.model_dump(), "business": business}
    provider, client = gateway([{"pages": [5, 18]}, draft, draft])
    plan = PresentationPlan(title="Document review")
    ensure_company_introduction(provider, source, plan)
    assert [item.model_dump() for item in plan.company.summary_business.items] == [original]
    ensure_company_introduction(provider, source, plan)
    assert len(client.calls) == 3


def test_unverified_numeric_page_title_cannot_survive_partial_salvage():
    source, company = source_only()
    overview = company.summary_overview.model_dump()
    overview["title"] = "Revenue increased 99999%"
    draft = {"overview": overview, "business": company.summary_business.model_dump()}
    provider, _ = gateway([{"pages": [5, 18]}, draft, draft])
    plan = PresentationPlan(title="Document review")
    ensure_company_introduction(provider, source, plan)
    assert plan.company.summary_overview is None
    assert plan.company.summary_business == company.summary_business
    assert not validate_summary(plan.company, source)
