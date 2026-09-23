"""Hierarchical document discovery through the provider-independent gateway."""

import re
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field

from adaptive_document_agent.models import AnalysisPageRange, DocumentProfile, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.utils.chunking import DocumentChunk, semantic_chunks
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.hashing import sha256_bytes

from .prompting import load_prompt, untrusted_document_message


class ChunkDiscovery(BaseModel):
    summary: str
    important_sections: list[str] = Field(default_factory=list)
    time_periods: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    important_tables: list[str] = Field(default_factory=list)
    important_figures: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)


class DocumentRoute(BaseModel):
    selected_page_ranges: list[AnalysisPageRange] = Field(default_factory=list)


class RouteBudgetSelection(BaseModel):
    """Model-ranked primary ranges when initial routing is too broad."""

    primary_range_indexes: list[int] = Field(default_factory=list, min_length=1, max_length=4)


class DocumentDiscovery:
    def __init__(self, gateway: LLMGateway | None = None, *, target_tokens: int = 6_000, cache: DiskCache | None = None) -> None:
        self.gateway = gateway
        self.target_tokens = target_tokens
        self.cache = cache

    def discover(
        self,
        document: ParsedDocument,
        *,
        analysis_focus: str | None = None,
        progress: Callable[[str], None] | None = None,
        routed_ranges: list[AnalysisPageRange] | None = None,
    ) -> DocumentProfile:
        notify = progress or (lambda _: None)
        if not self.gateway:
            chunks = semantic_chunks(document.pages, target_tokens=self.target_tokens)
            profile = self._deterministic_profile(document, chunks)
            profile.analysis_focus = analysis_focus.strip() if analysis_focus and analysis_focus.strip() else None
            return profile
        if routed_ranges is None and (document.page_count > 160 or self._estimated_chunk_count(document.pages) > 24):
            notify("Mapping the large document and selecting relevant sections")
            routed_ranges = self._route_large_document(document, analysis_focus)
        routed_ranges = routed_ranges or []
        if routed_ranges:
            # Build heavy chunk text only for deep-analysis pages. The full
            # page-preserving document remains available for background facts.
            chunks = [
                chunk
                for item in routed_ranges
                for chunk in semantic_chunks(
                    [page for page in document.pages if item.start_page <= page.page_number <= item.end_page],
                    target_tokens=self.target_tokens,
                )
            ]
            chunks = self._select_chunks(chunks, routed_ranges)
        else:
            chunks = semantic_chunks(document.pages, target_tokens=self.target_tokens)
        discoveries = self._discover_chunks(chunks, notify)
        compact = "\n".join(
            f"Pages {chunk.start_page}-{chunk.end_page}: {discovery.model_dump_json()}"
            for chunk, discovery in zip(chunks, discoveries, strict=True)
        )
        notify("Merging selected sections into the global document profile")
        messages = [
                {"role": "system", "content": load_prompt("document_discovery.txt")},
        ]
        if analysis_focus and analysis_focus.strip():
            messages.append(
                {
                    "role": "user",
                    "content": "Use this user-supplied analysis focus to prioritise the profile's metrics and dimensions, without inventing absent data: " + analysis_focus.strip(),
                }
            )
        messages.append(untrusted_document_message(compact))
        profile = self.gateway.generate_structured(
            messages,
            DocumentProfile,
            stage="discovery",
        )
        reviewed_pages = {
            page
            for chunk in chunks
            for page in range(chunk.start_page, chunk.end_page + 1)
        }
        profile.document_summary_pages = sorted({
            page for page in profile.document_summary_pages if page in reviewed_pages
        })
        profile.analysis_focus = analysis_focus.strip() if analysis_focus and analysis_focus.strip() else None
        profile.analysis_page_ranges = [(item.start_page, item.end_page) for item in routed_ranges]
        for item in routed_ranges:
            if item.title not in profile.important_sections:
                profile.important_sections.append(item.title)
        return profile

    def _discover_chunks(self, chunks: list[DocumentChunk], notify: Callable[[str], None]) -> list[ChunkDiscovery]:
        workers = min(getattr(self.gateway, "discovery_workers", 1), len(chunks))
        if workers <= 1:
            discoveries = []
            for index, chunk in enumerate(chunks, 1):
                notify(f"Understanding selected pages {chunk.start_page}-{chunk.end_page} ({index}/{len(chunks)})")
                discoveries.append(self._discover_chunk(chunk))
            return discoveries
        # Results are merged in source order, never completion order. Progress
        # callbacks (including Streamlit) run only on the calling/UI thread.
        discoveries_by_index: dict[int, ChunkDiscovery] = {}
        notify(f"Understanding selected sections with {workers} concurrent requests")
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="discovery") as pool:
            futures = {pool.submit(self._discover_chunk, chunk): index for index, chunk in enumerate(chunks)}
            try:
                for future in as_completed(futures):
                    index = futures[future]
                    discoveries_by_index[index] = future.result()
                    chunk = chunks[index]
                    notify(f"Understood selected pages {chunk.start_page}-{chunk.end_page} ({len(discoveries_by_index)}/{len(chunks)})")
            except Exception:
                for future in futures:
                    future.cancel()
                raise  # Never merge an incomplete/failed discovery as success.
        return [discoveries_by_index[index] for index in range(len(chunks))]

    def route(self, document: ParsedDocument, analysis_focus: str | None = None) -> list[AnalysisPageRange]:
        """Select a bounded scope that can be reviewed before deep analysis."""
        if self.gateway and (document.page_count > 160 or self._estimated_chunk_count(document.pages) > 24):
            selected = self._route_large_document(document, analysis_focus)
            if selected:
                return selected
        return [
            AnalysisPageRange(
                title="Complete document",
                start_page=1,
                end_page=document.page_count,
                reason="The document is small enough to analyse as a complete page-preserving scope.",
            )
        ]

    def _estimated_chunk_count(self, pages: list) -> int:
        estimated_tokens = sum(max(1, len(page.text) // 4) for page in pages)
        return max(1, (estimated_tokens + self.target_tokens - 1) // self.target_tokens)

    def _route_large_document(self, document: ParsedDocument, analysis_focus: str | None) -> list[AnalysisPageRange]:
        page_map: list[str] = []
        for page in document.pages:
            lines = [" ".join(line.split()) for line in page.text.splitlines() if line.strip()]
            headings = [line for line in lines[:12] if 3 <= len(line) <= 100 and (line.isupper() or line.istitle())][:3]
            preview = " ".join(lines[:4])[:220]
            page_map.append(f"Page {page.page_number} | headings={headings} | preview={preview}")
        focus_message = analysis_focus.strip() if analysis_focus and analysis_focus.strip() else "Identify the most decision-useful sections for evidence-backed analysis."
        route = self.gateway.generate_structured(  # type: ignore[union-attr]
            [
                {"role": "system", "content": load_prompt("document_routing.txt")},
                {"role": "user", "content": f"Analysis focus supplied by the user: {focus_message}"},
                untrusted_document_message("\n".join(page_map)),
            ],
            DocumentRoute,
            stage="discovery",
        )
        maximum_page = len(document.pages)
        output: list[AnalysisPageRange] = []
        for item in route.selected_page_ranges[:12]:
            start, end = max(1, item.start_page), min(maximum_page, item.end_page)
            if start <= end:
                output.append(item.model_copy(update={"start_page": start, "end_page": end}))
        if not output:
            raise ValueError("No valid evidence-bearing page range was selected for deep analysis")
        if sum(item.end_page - item.start_page + 1 for item in output) > 160:
            excerpts = []
            for index, item in enumerate(output):
                sample_pages = {item.start_page, (item.start_page + item.end_page) // 2, item.end_page}
                excerpts.append({
                    "index": index,
                    "title": item.title,
                    "start_page": item.start_page,
                    "end_page": item.end_page,
                    "reason": item.reason,
                    "page_excerpts": [
                        {"page": page.page_number, "text": " ".join(page.text.split())[:350]}
                        for page in document.pages if page.page_number in sample_pages
                    ],
                })
            narrowed = self.gateway.generate_structured(  # type: ignore[union-attr]
                [
                    {"role": "system", "content": load_prompt("document_route_budget.txt")},
                    {"role": "user", "content": "User analysis focus: " + (analysis_focus.strip() if analysis_focus else "Automatic discovery")},
                    untrusted_document_message(json.dumps(excerpts, ensure_ascii=False)),
                ],
                RouteBudgetSelection,
                stage="discovery",
            )
            indices = narrowed.primary_range_indexes
            if len(indices) != len(set(indices)) or any(index < 0 or index >= len(output) for index in indices):
                raise ValueError("The primary section selection contains invalid range indexes")
            primary = [output[index] for index in indices]
            if sum(item.end_page - item.start_page + 1 for item in primary) > 160:
                raise ValueError("The primary section selection exceeds the deep-analysis page budget")
            output = sorted(primary, key=lambda item: item.start_page)
        return output

    @staticmethod
    def _select_chunks(chunks: list[DocumentChunk], ranges: list[AnalysisPageRange], *, maximum: int = 32) -> list[DocumentChunk]:
        selected = [
            chunk
            for chunk in chunks
            if any(chunk.start_page <= item.end_page and chunk.end_page >= item.start_page for item in ranges)
        ]
        if selected:
            if len(selected) <= maximum:
                return selected
            # Sample the whole selected scope, including late sections, rather
            # than silently dropping everything after the first 32 chunks.
            return [selected[round(index * (len(selected) - 1) / (maximum - 1))]
                    for index in range(maximum)]
        if len(chunks) <= maximum:
            return chunks
        step = len(chunks) / maximum
        return [chunks[min(int(index * step), len(chunks) - 1)] for index in range(maximum)]

    def _discover_chunk(self, chunk: DocumentChunk) -> ChunkDiscovery:
        prompt = load_prompt("document_discovery.txt")
        cache_key = None
        if self.cache is not None and self.gateway is not None:
            settings = self.gateway.settings
            identity = {
                "version": "chunk-discovery-v1",
                "prompt": prompt,
                "schema": ChunkDiscovery.model_json_schema(),
                "chunk": chunk.model_dump(mode="json"),
                "provider": settings.provider.value,
                "model": settings.model_for("discovery"),
                "endpoint": settings.base_url,
                "privacy_mode": settings.privacy_mode.value,
                "temperature": settings.temperature,
            }
            # Only the hash is used as a filename. No API keys are persisted.
            cache_key = "chunk-discovery-" + sha256_bytes(json.dumps(identity, sort_keys=True).encode())
            cached = self.cache.get_model(cache_key, ChunkDiscovery)
            if cached is not None:
                return cached
        discovery = self.gateway.generate_structured(  # type: ignore[union-attr]
            [
                {"role": "system", "content": prompt},
                untrusted_document_message(chunk.text),
            ],
            ChunkDiscovery,
            stage="discovery",
        )
        if cache_key is not None:
            self.cache.set_model(cache_key, discovery)
        return discovery

    def _deterministic_profile(self, document: ParsedDocument, chunks: list[DocumentChunk]) -> DocumentProfile:
        text = "\n".join(page.text for page in document.pages)
        periods = sorted(set(re.findall(r"\b(?:19|20)\d{2}\b", text)))
        currencies = [name for name, pattern in {"USD": r"\$|\bUSD\b", "GBP": r"£|\bGBP\b", "EUR": r"€|\bEUR\b", "CNY": r"\b(?:CNY|RMB)\b"}.items() if re.search(pattern, text, re.I)]
        sections = list(dict.fromkeys(hint for chunk in chunks for hint in chunk.section_hints))[:30]
        table_count = sum(len(page.tables) for page in document.pages)
        notes = list(document.warnings)
        if not text.strip():
            notes.append("No digital text was extracted; OCR may be required.")
        return DocumentProfile(
            document_type="Unclassified PDF (LLM discovery unavailable)",
            document_purpose="Requires semantic model discovery",
            important_sections=sections,
            detected_time_periods=periods,
            detected_currencies=currencies,
            important_tables=[f"{table_count} digitally extracted table(s)"] if table_count else [],
            important_figures=[image.image_id for page in document.pages for image in page.images],
            data_quality_notes=notes,
        )
