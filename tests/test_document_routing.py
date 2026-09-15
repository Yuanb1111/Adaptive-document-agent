from adaptive_document_agent.agent.document_discovery import DocumentDiscovery
from adaptive_document_agent.models import DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName


def test_large_document_routes_to_user_relevant_page_ranges_before_deep_discovery() -> None:
    document = ParsedDocument(
        document_id="document_test",
        sha256="0" * 64,
        safe_filename="document_test.pdf",
        page_count=30,
        pages=[
            DocumentPage(page_number=page, text=f"SECTION {page}\nRepresentative page content " * 8, extraction_quality=1.0)
            for page in range(1, 31)
        ],
    )
    responses = [
        {
            "selected_page_ranges": [
                {"title": "Relevant evidence", "start_page": 10, "end_page": 11, "reason": "Matches the user focus."}
            ]
        },
        {"summary": "Page 10 evidence"},
        {"summary": "Page 11 evidence"},
        {
            "document_type": "Unseen document",
            "document_purpose": "Evaluate selected evidence",
            "document_summary": "The selected pages describe the relevant evidence.",
            "document_summary_pages": [10, 99],
        },
    ]
    client = MockLLMClient(responses)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    profile = DocumentDiscovery(gateway, target_tokens=20).discover(document, analysis_focus="Find the relevant evidence")
    assert profile.analysis_page_ranges == [(10, 11)]
    assert profile.analysis_focus == "Find the relevant evidence"
    assert profile.document_summary_pages == [10]
    assert "Relevant evidence" in profile.important_sections
    assert len(client.calls) == 4
    assert "Analysis focus supplied by the user" in client.calls[0][1]["content"]
    assert "Use this user-supplied analysis focus" in client.calls[-1][1]["content"]
