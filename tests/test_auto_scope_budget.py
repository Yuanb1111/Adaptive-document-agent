"""Large-document routing must protect late primary evidence from early-page truncation."""

import pytest

from adaptive_document_agent.agent.document_discovery import DocumentDiscovery
from adaptive_document_agent.models import AnalysisPageRange, DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.utils.chunking import DocumentChunk


def test_overbroad_route_requires_model_ranked_primary_scope() -> None:
    document = ParsedDocument(
        document_id="large", sha256="0" * 64, safe_filename="large.pdf", page_count=240,
        pages=[DocumentPage(page_number=page, text=f"Section evidence on page {page}")
               for page in range(1, 241)],
    )
    client = MockLLMClient([
        {"selected_page_ranges": [
            {"title": "Context", "start_page": 1, "end_page": 100, "reason": "Background"},
            {"title": "Additional context", "start_page": 101, "end_page": 165, "reason": "Background"},
            {"title": "Primary evidence", "start_page": 166, "end_page": 240, "reason": "Reported measurements"},
        ]},
        {"primary_range_indexes": [2]},
    ])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    selected = DocumentDiscovery(gateway)._route_large_document(document, None)
    assert [(item.start_page, item.end_page) for item in selected] == [(166, 240)]
    assert len(client.calls) == 2
    assert "Primary evidence" in client.calls[1][-1]["content"]


def test_overbroad_route_rejects_budget_violation() -> None:
    document = ParsedDocument(
        document_id="large", sha256="0" * 64, safe_filename="large.pdf", page_count=240,
        pages=[DocumentPage(page_number=page, text=f"Page {page}") for page in range(1, 241)],
    )
    client = MockLLMClient([
        {"selected_page_ranges": [
            {"title": "First", "start_page": 1, "end_page": 100, "reason": "Evidence"},
            {"title": "Second", "start_page": 101, "end_page": 240, "reason": "Evidence"},
        ]},
        {"primary_range_indexes": [0, 1]},
    ])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK, model="mock"))
    with pytest.raises(ValueError, match="page budget"):
        DocumentDiscovery(gateway)._route_large_document(document, None)


def test_chunk_cap_samples_late_selected_pages() -> None:
    chunks = [DocumentChunk(
        chunk_id=f"chunk-{page}", start_page=page, end_page=page,
        estimated_tokens=5, text=f"Page {page}",
    ) for page in range(1, 101)]
    ranges = [AnalysisPageRange(
        title="Complete primary evidence", start_page=1, end_page=100,
        reason="Evidence-bearing section",
    )]
    selected = DocumentDiscovery._select_chunks(chunks, ranges, maximum=8)
    assert len(selected) == 8
    assert selected[0].start_page == 1
    assert selected[-1].end_page == 100
    assert any(item.start_page > 80 for item in selected)
