"""Bounded overview synthesis does not regenerate source inventories."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.discovery_compaction import overview_context
from adaptive_document_agent.agent.document_discovery import ChunkDiscovery, DiscoveryOverview, DocumentDiscovery
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMTransportError
from adaptive_document_agent.utils.chunking import DocumentChunk


@pytest.mark.parametrize("payload", [
    {"document_summary": "x" * 1201},
    {"overview_points": ["a", "b", "c", "d"]},
    {"overview_points": ["x" * 221]},
    {"document_summary_pages": list(range(1, 26))},
    {"document_summary_pages": [True]},
    {"data_quality_notes": ["a"] * 5},
    {"data_quality_notes": ["x" * 241]},
    {"important_tables": ["Repeated inventory"]},
])
def test_overview_schema_rejects_long_or_inventory_output(payload):
    with pytest.raises(ValidationError):
        DiscoveryOverview.model_validate(payload)


def source_chunks():
    chunks = [DocumentChunk(chunk_id=f"c{i}", start_page=start, end_page=end,
                            text=f"Original source {i}", estimated_tokens=10)
              for i, (start, end) in enumerate([(2, 4), (8, 9)])]
    discoveries = [ChunkDiscovery(
        summary=f"Supported subject summary {i}", important_sections=["Shared section", f"Section {i}"],
        metrics=[f"Exact metric {i}/{j}" for j in range(300)],
        important_tables=[f"Table {i}"], data_quality_notes=[f"Original quality note {i}"],
    ) for i in range(2)]
    return chunks, discoveries


def test_overview_context_keeps_every_summary_page_and_section_without_full_inventory():
    chunks, discoveries = source_chunks()
    before = [item.model_dump() for item in discoveries]
    payload = json.loads(overview_context(chunks, discoveries))
    assert [item["pages"] for item in payload["chunks"]] == [[2, 4], [8, 9]]
    assert [item["summary"] for item in payload["chunks"]] == [item.summary for item in discoveries]
    assert payload["section_catalog"] == {"Shared section": [0, 1], "Section 0": [0], "Section 1": [1]}
    assert "Exact metric" not in json.dumps(payload)
    assert "Original quality note" not in json.dumps(payload)
    assert [item.model_dump() for item in discoveries] == before


def test_oversized_schema_output_gets_one_source_grounded_overview_retry():
    chunks, discoveries = source_chunks()
    client = MockLLMClient([
        {"document_summary": "Repeated prose " * 200},
        {"document_summary": "Supported subject summary.", "document_summary_pages": [2, 8]},
    ])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    overview = DocumentDiscovery(gateway)._synthesize_overview(chunks, discoveries, None)
    assert overview.document_summary_pages == [2, 8]
    assert len(client.calls) == 2
    assert [item["status"] for item in gateway.usage] == ["invalid_format", "success"]
    assert all(item["operation"] == "DiscoveryOverview" for item in gateway.usage)
    assert client.calls[0][-1] == client.calls[1][-2]
    assert "Repeated prose" not in json.dumps(client.calls[1])


def test_overview_transport_failure_does_not_trigger_semantic_recovery():
    chunks, discoveries = source_chunks()
    gateway = SimpleNamespace(generate_structured=Mock(side_effect=LLMTransportError("unavailable")))
    with pytest.raises(LLMTransportError, match="unavailable"):
        DocumentDiscovery(gateway)._synthesize_overview(chunks, discoveries, None)
    assert gateway.generate_structured.call_count == 1
