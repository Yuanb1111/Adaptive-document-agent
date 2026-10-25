"""Overview citations follow reviewed evidence, independently of prose length."""

import pytest
from pydantic import ValidationError

from adaptive_document_agent.agent.document_discovery import ChunkDiscovery, DiscoveryOverview, DocumentDiscovery
from adaptive_document_agent.models import DocumentPage, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway, LLMSettings, MockLLMClient, ProviderName
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.chunking import DocumentChunk


@pytest.mark.parametrize('count', [24, 25, 26, 80])
def test_complete_citation_lists_do_not_trigger_repair_or_lose_pages(count, tmp_path):
    pages = list(range(1, count + 1))
    answer = {'document_summary': 'Supported source overview.', 'document_summary_pages': pages}
    client = MockLLMClient([answer])
    cache = DiskCache(tmp_path)
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK), cache=cache)
    discovery = DocumentDiscovery(gateway, cache=cache)
    chunks = [DocumentChunk(chunk_id='all', start_page=1, end_page=count,
                            text='Source material.', estimated_tokens=10)]
    summaries = [ChunkDiscovery(summary='Supported source overview.')]
    first = discovery._synthesize_overview(chunks, summaries, None)
    assert first.document_summary_pages == pages
    assert len(client.calls) == 1 and gateway.usage[0]['status'] == 'success'
    assert discovery._synthesize_overview(chunks, summaries, None) == first
    assert len(client.calls) == 1 and gateway.usage[-1]['cache_hit']
    schema = DiscoveryOverview.model_json_schema()['properties']['document_summary_pages']
    assert 'maxItems' not in schema and schema['items']['minimum'] == 1


@pytest.mark.parametrize('page', [True, False, 0, -1, 1.5, '2', '2-4', None])
def test_more_citations_does_not_relax_page_types_or_positive_bounds(page):
    with pytest.raises(ValidationError):
        DiscoveryOverview(document_summary_pages=[*range(1, 27), page])


def test_discovery_retains_all_reviewed_citations_but_not_duplicates_or_outside_pages(monkeypatch):
    pages = list(range(1, 41))
    document = ParsedDocument(document_id='source', sha256='source', safe_filename='source.pdf', page_count=40,
        pages=[DocumentPage(page_number=p, text=f'Source text on PDF page {p}.') for p in pages])
    snapshot = document.model_dump()
    client = MockLLMClient([{'document_summary': 'Supported source overview.',
                           'document_summary_pages': [*reversed(pages), 1, 40, 41, 999]}])
    gateway = LLMGateway(client, LLMSettings(provider=ProviderName.MOCK))
    discovery = DocumentDiscovery(gateway, target_tokens=12000)
    monkeypatch.setattr(discovery, '_discover_chunks', lambda chunks, notify: [
        ChunkDiscovery(summary='Supported source overview.', metrics=['Unchanged metric inventory']) for c in chunks])
    profile = discovery.discover(document)
    assert profile.document_summary_pages == pages
    assert profile.metrics == ['Unchanged metric inventory']
    assert len(client.calls) == 1 and document.model_dump() == snapshot
