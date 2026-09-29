"""Source-quoted operating flows stay optional and editable."""

from adaptive_document_agent.models import (
    CompanyProfile, DocumentPage, DocumentProfile, ParsedDocument, PipelineResult,
)
from adaptive_document_agent.models.presentation import CompanySummaryItem
from adaptive_document_agent.services.company_summary import validate_summary
from adaptive_document_agent.services.presentation_value_chain import can_render_value_chain, render_value_chain
from tests.test_presentation_brief import blank_deck


def _company():
    passages = [
        "The service provides access to shared equipment.",
        "Regional operators purchase access for their teams.",
        "The company earns fees under annual service contracts.",
    ]
    company = CompanyProfile(value_chain=[
        CompanySummaryItem(label=label, text=passage, source_pages=[1], source_quote=passage)
        for label, passage in zip(("Service", "Customers", "Revenue"), passages)
    ], source_pages=[1])
    result = PipelineResult(
        document=ParsedDocument(document_id="generic", sha256="x" * 64, safe_filename="source.pdf",
                                page_count=1, pages=[DocumentPage(page_number=1, text="\n".join(passages))]),
        profile=DocumentProfile(),
    )
    return company, result


def test_model_selected_value_chain_is_source_checked_and_renders_flat_flow():
    company, result = _company()
    assert not validate_summary(company, result)
    deck = blank_deck()
    assert can_render_value_chain(company, deck.slide_width.inches)
    slide = render_value_chain(deck, company)
    assert slide is not None
    assert [s.text for s in slide.shapes if s.name == "value_chain:label"] == [
        "Service", "Customers", "Revenue",
    ]
    assert "source_quote" in slide.notes_slide.notes_text_frame.text


def test_value_chain_rejects_unquoted_numeric_claim():
    company, result = _company()
    company.value_chain[0].text = "The service provides access to 12 shared devices."
    assert any("unsupported numeric claims" in issue for issue in validate_summary(company, result))
