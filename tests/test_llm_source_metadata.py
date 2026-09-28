"""Source locators survive billing and cache paths without entering model calls."""

import csv
import io
from unittest.mock import Mock

import pytest

from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMTransportError
from adaptive_document_agent.services.llm.litellm_provider import LiteLLMProvider
from adaptive_document_agent.services.llm.usage_export import export_usage_csv
from adaptive_document_agent.utils.caching import DiskCache
from tests.test_llm_costs import Answer, raw_response


def source_metadata():
    return {"chunk_id": "chunk-synthetic", "source_page_start": 8, "source_page_end": 12,
            "parent_chunk_id": "parent-synthetic", "fragment_index": 1,
            "fragment_count": 2, "recovery_depth": 1}


def test_source_locators_are_ledger_only_and_do_not_invalidate_cache(tmp_path):
    client = MockLLMClient([{"value": 7}])
    generate = Mock(wraps=client.generate_structured)
    client.generate_structured = generate
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK), cache=DiskCache(tmp_path))
    metadata = source_metadata()
    assert gateway.generate_structured([], Answer, stage="discovery", request_metadata=metadata).value == 7
    second = {**metadata, "chunk_id": "another-source", "source_page_start": 20, "source_page_end": 24}
    assert gateway.generate_structured([], Answer, stage="discovery", request_metadata=second).value == 7
    assert generate.call_count == 1
    assert "request_metadata" not in generate.call_args.kwargs
    assert gateway.usage[0]["chunk_id"] == metadata["chunk_id"]
    assert gateway.usage[1]["chunk_id"] == second["chunk_id"]
    assert gateway.usage[1]["cache_hit"] and gateway.usage[1]["output_tokens"] == 0
    rows = list(csv.DictReader(io.StringIO(export_usage_csv(gateway.usage).decode("utf-8-sig"))))
    for key, value in metadata.items():
        assert rows[0][key] == str(value)
    assert rows[1]["source_page_start"] == "20"


def test_truncation_identifies_source_without_duplicating_usage(monkeypatch):
    settings = LLMSettings()
    provider = LiteLLMProvider(settings)
    response = raw_response(finish="length")
    response.usage.completion_tokens = 8192
    complete = Mock(return_value=response)
    monkeypatch.setattr(provider, "_completion", complete)
    gateway = LLMGateway(provider, settings)
    metadata = {**source_metadata(), "status": "success", "output_tokens": 0, "document_text": "private source"}
    with pytest.raises(LLMStructuredOutputError) as failure:
        gateway.generate_structured([], Answer, stage="discovery", request_metadata=metadata)
    assert "source pages: 8-12" in str(failure.value)
    assert "chunk: chunk-synthetic" in str(failure.value)
    assert "output tokens: 8192" in str(failure.value)
    assert complete.call_count == len(gateway.usage) == 1
    assert gateway.usage[0]["status"] == "truncated" and gateway.usage[0]["output_tokens"] == 8192
    assert "document_text" not in gateway.usage[0]
    assert "private source" not in str(complete.call_args)


def test_format_repair_keeps_source_locators_on_both_requests():
    gateway = LLMGateway(MockLLMClient(["invalid JSON", '{"value":9}']), LLMSettings(provider=ProviderName.MOCK))
    result = gateway.generate_structured([], Answer, stage="discovery", request_metadata=source_metadata())
    assert result.value == 9
    assert [row["status"] for row in gateway.usage] == ["invalid_format", "format_repair"]
    assert all(row["chunk_id"] == "chunk-synthetic" and row["source_page_end"] == 12 for row in gateway.usage)


def test_transport_error_keeps_source_and_unknown_billing():
    client = MockLLMClient()
    client.generate_structured = Mock(side_effect=LLMTransportError("provider unavailable"))
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    with pytest.raises(LLMTransportError):
        gateway.generate_structured([], Answer, stage="discovery", request_metadata=source_metadata())
    assert len(gateway.usage) == 1
    assert gateway.usage[0]["chunk_id"] == "chunk-synthetic"
    assert gateway.usage[0]["estimated_cost"] is None
    assert gateway.usage[0]["output_tokens"] is None
