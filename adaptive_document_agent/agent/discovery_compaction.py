"""Lossless structural deduplication; no semantic merging or metric truncation."""

import json
from typing import TYPE_CHECKING
from adaptive_document_agent.utils.chunking import DocumentChunk

if TYPE_CHECKING:
    from .document_discovery import ChunkDiscovery


def compact_discoveries(chunks: list[DocumentChunk], discoveries: list["ChunkDiscovery"]) -> str:
    catalog = {}
    summaries = []
    for index, (chunk, discovery) in enumerate(zip(chunks, discoveries, strict=True)):
        summaries.append({"chunk": index, "pages": [chunk.start_page, chunk.end_page],
                          "summary": discovery.summary})
        for field, values in discovery.model_dump().items():
            if field == "summary":
                continue
            entries = catalog.setdefault(field, {})
            for value in values:
                sources = entries.setdefault(value, [])
                if index not in sources:
                    sources.append(index)
    return json.dumps({"chunks": summaries, "catalog": catalog,
                       "catalog_format": "field -> exact source term -> source chunk indexes; pages are in chunks. Preserve every metric; do not merge different terms or suppress conflicts."},
                      ensure_ascii=False, separators=(",", ":"))
