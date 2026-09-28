"""Hierarchical document discovery through the provider-independent gateway."""

import re
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from adaptive_document_agent.models import AnalysisPageRange, DocumentProfile, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.utils.chunking import DocumentChunk, semantic_chunks
from adaptive_document_agent.utils.caching import DiskCache
from adaptive_document_agent.utils.hashing import sha256_bytes

from .prompting import load_prompt, untrusted_document_message
from .route_budget import (
    DEEP_ANALYSIS_PAGE_BUDGET, RouteBudgetSelection, contiguous_spans,
    covered_pages, fit_ranked_ranges, ranked_ranges,
)


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


class DiscoveryOverview(BaseModel):
    """Only semantic synthesis is generated again; inventories stay in Python."""

    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(default="Unknown document", max_length=120)
    document_purpose: str = Field(default="Not yet determined", max_length=400)
    overview_title: str = Field(default="Document overview", max_length=160)
    document_summary: str = Field(default="", max_length=1200)
    document_summary_pages: list[Annotated[StrictInt, Field(ge=1)]] = Field(default_factory=list, max_length=24)
    overview_points: list[Annotated[str, Field(max_length=220)]] = Field(default_factory=list, max_length=3)
    language: str | None = Field(default=None, max_length=40)
    data_quality_notes: list[Annotated[str, Field(max_length=240)]] = Field(default_factory=list, max_length=4)


class DocumentRoute(BaseModel):
    selected_page_ranges: list[AnalysisPageRange] = Field(default_factory=list)


class DocumentDiscovery:
    def __init__(self, gateway: LLMGateway | None = None, *, target_tokens: int | None = None, cache: DiskCache | None = None) -> None:
        self.gateway = gateway
        self.target_tokens = target_tokens or 6000
        if target_tokens is None and isinstance(gateway, LLMGateway) and gateway.discovery_workers > 1:
            self.target_tokens = gateway.settings.discovery_chunk_tokens
            context = gateway.client.capabilities.max_context_tokens
            if context is not None:
                # Reserve half the declared context for schema, response and
                # token-estimation error. Local/stateful clients keep 6k chunks.
                self.target_tokens = min(self.target_tokens, max(1000, context // 2))
        self.cache = cache
        self._source_pages = []

    def discover(
        self,
        document: ParsedDocument,
        *,
        analysis_focus: str | None = None,
        progress: Callable[[str], None] | None = None,
        routed_ranges: list[AnalysisPageRange] | None = None,
    ) -> DocumentProfile:
        notify = progress or (lambda _: None)
        # Replace on every document, including reused discovery instances.
        # Recovery obtains physical page boundaries here, never from PDF text.
        self._source_pages = list(document.pages)
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
                for start, end in contiguous_spans(covered_pages(routed_ranges))
                for chunk in semantic_chunks(
                    [page for page in document.pages if start <= page.page_number <= end],
                    target_tokens=self.target_tokens,
                )
            ]
            # All pages in the confirmed scope remain covered. Larger bounded
            # chunks reduce request waves without sampling away late evidence.
        else:
            chunks = semantic_chunks(document.pages, target_tokens=self.target_tokens)
        discoveries = self._discover_chunks(chunks, notify)
        notify("Merging selected sections into the global document profile")
        overview = self._synthesize_overview(chunks, discoveries, analysis_focus)
        profile = DocumentProfile.model_validate(overview.model_dump())
        reviewed_pages = {
            page
            for chunk in chunks
            for page in range(chunk.start_page, chunk.end_page + 1)
        }
        profile.document_summary_pages = sorted({
            page for page in profile.document_summary_pages if page in reviewed_pages
        })
        profile.analysis_focus = analysis_focus.strip() if analysis_focus and analysis_focus.strip() else None
        # The model ranks/interprets; it must not erase the discovered inventory.
        for discovery in discoveries:
            for field, source in (("metrics", "metrics"), ("detected_units", "units"),
                                  ("detected_time_periods", "time_periods"),
                                  ("detected_currencies", "currencies"), ("entities", "entities"),
                                  ("dimensions", "dimensions"), ("data_quality_notes", "data_quality_notes"),
                                  ("important_sections", "important_sections"),
                                  ("important_tables", "important_tables"),
                                  ("important_figures", "important_figures")):
                target = getattr(profile, field)
                target.extend(value for value in getattr(discovery, source) if value not in target)
        profile.analysis_page_ranges = [(item.start_page, item.end_page) for item in routed_ranges]
        for item in routed_ranges:
            if item.title not in profile.important_sections:
                profile.important_sections.append(item.title)
        return profile

    def _synthesize_overview(
        self, chunks: list[DocumentChunk], discoveries: list[ChunkDiscovery],
        analysis_focus: str | None,
    ) -> DiscoveryOverview:
        """Generate bounded prose, retrying only this synthesis once if invalid."""
        from .discovery_compaction import overview_context

        messages = [{"role": "system", "content": load_prompt("discovery_overview.txt")}]
        if analysis_focus and analysis_focus.strip():
            messages.append({"role": "user", "content":
                "Use this user-supplied analysis focus to prioritise supported overview evidence only: " + analysis_focus.strip()})
        messages.append(untrusted_document_message(overview_context(chunks, discoveries)))

        # A successful compact retry must also satisfy the next ordinary run.
        # Gateway message caches alone use different keys for the two attempts.
        cache = self.cache or getattr(self.gateway, "cache", None)
        cache_key = None
        if cache is not None and isinstance(self.gateway, LLMGateway) and self.gateway.cache_enabled:
            settings = self.gateway.settings
            identity = {
                "version": "discovery-overview-v1", "messages": messages,
                "schema": DiscoveryOverview.model_json_schema(),
                "provider": settings.provider.value, "model": settings.model_for("discovery"),
                "endpoint": settings.base_url, "privacy_mode": settings.privacy_mode.value,
                "temperature": settings.temperature, "discovery_thinking": settings.discovery_thinking,
            }
            cache_key = "discovery-overview-" + sha256_bytes(
                json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            cached = cache.get_model(cache_key, DiscoveryOverview)
            if cached is not None:
                self.gateway.record_cache_hit(stage="discovery", operation="DiscoveryOverview")
                return cached

        for attempt in range(2):
            request = messages
            if attempt:
                request = [*messages, {"role": "user", "content": (
                    "The previous overview was incomplete or did not match the bounded schema. "
                    "Regenerate one compact, complete JSON overview from the supplied source summaries. "
                    "Use at most 80 words for document_summary and at most two short overview_points. "
                    "Return no inventories or repeated section/table/figure labels. "
                    "Use empty data_quality_notes unless a new cross-section limitation is essential. "
                    "Do not complete or guess missing text from a previous answer; use source evidence only."
                )}]
            try:
                overview = self.gateway.generate_structured(  # type: ignore[union-attr]
                    request, DiscoveryOverview, stage="discovery", allow_repair=False,
                )
            except (LLMStructuredOutputError, ValidationError):
                if attempt:
                    raise
                continue
            if cache_key is not None:
                cache.set_model(cache_key, overview)
            return overview
        raise AssertionError("Overview recovery attempts exhausted without a result or exception")

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
        available_pages = {page.page_number for page in document.pages}
        maximum_page = max(available_pages, default=0)
        output: list[AnalysisPageRange] = []
        for item in route.selected_page_ranges[:12]:
            start, end = max(1, item.start_page), min(maximum_page, item.end_page)
            if start <= end and set(range(start, end + 1)) <= available_pages:
                output.append(item.model_copy(update={"start_page": start, "end_page": end}))
        if not output:
            raise ValueError("No valid evidence-bearing page range was selected for deep analysis")
        if len(covered_pages(output)) > DEEP_ANALYSIS_PAGE_BUDGET:
            excerpts = []
            for index, item in enumerate(output):
                sample_pages = {item.start_page, (item.start_page + item.end_page) // 2, item.end_page}
                excerpts.append({
                    "index": index,
                    "title": item.title,
                    "start_page": item.start_page,
                    "end_page": item.end_page,
                    "page_count": item.end_page - item.start_page + 1,
                    "reason": item.reason,
                    "page_excerpts": [
                        {"page": page.page_number, "text": " ".join(page.text.split())[:350]}
                        for page in document.pages if page.page_number in sample_pages
                    ],
                })
                if item.end_page - item.start_page + 1 > DEEP_ANALYSIS_PAGE_BUDGET:
                    # Only an oversized candidate needs a denser boundary map.
                    # The model, not Python, chooses its complete subsections.
                    excerpts[-1]["page_map"] = [
                        {"page": page.page_number, "preview": " ".join(page.text.split())[:120]}
                        for page in document.pages if item.start_page <= page.page_number <= item.end_page
                    ]
            output = self._budget_route(output, excerpts, analysis_focus)
        return output

    def _budget_route(self, candidates: list[AnalysisPageRange], excerpts: list[dict],
                      analysis_focus: str | None) -> list[AnalysisPageRange]:
        from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
        # Overlapping broad candidates must not duplicate the same boundary
        # context in the request. The full page text remains in the document.
        boundary_pages = {page["page"]: page for item in excerpts for page in item.get("page_map", [])}
        payload = {"ranges": [{key: value for key, value in item.items() if key != "page_map"}
                              for item in excerpts]}
        if boundary_pages:
            payload["oversized_range_page_map"] = [boundary_pages[page] for page in sorted(boundary_pages)]
        feedback = None
        for _ in range(2):
            messages = [
                {"role": "system", "content": load_prompt("document_route_budget.txt")},
                {"role": "user", "content": "User analysis focus: " + (analysis_focus.strip() if analysis_focus else "Automatic discovery")},
                untrusted_document_message(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            ]
            if feedback:
                messages.append({"role": "user", "content": feedback})
            try:
                narrowed = self.gateway.generate_structured(  # type: ignore[union-attr]
                    messages, RouteBudgetSelection, stage="discovery", allow_repair=False,
                )
                return fit_ranked_ranges(ranked_ranges(narrowed, candidates))
            except (ValueError, LLMStructuredOutputError):
                # One compact semantic retry, with no nested format-repair call.
                # Never silently truncate an oversized section or fall back to
                # analysing the whole document after an empty/invalid response.
                feedback = (
                    "The previous selection was empty, invalid, or retained an oversized primary range. "
                    "Return distinct valid indexes. For every selected range longer than 160 pages, "
                    "use refined_ranges to identify complete evidence subsections from its page map, "
                    "inside the original boundaries and within the 160-page budget. "
                    "Do not choose a prefix merely to meet the limit."
                )
        raise ValueError(
            "Could not select complete evidence sections within the 160-page deep-analysis budget "
            "after one refinement attempt. Narrow the analysis focus or confirm smaller complete "
            "sections; no partial section or full-document fallback was analysed."
        )

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
        prompt = load_prompt("chunk_discovery.txt")
        metadata = {"chunk_id": chunk.chunk_id, "source_page_start": chunk.start_page,
                    "source_page_end": chunk.end_page}
        cache = self.cache or getattr(self.gateway, "cache", None)
        cache_key = None
        if cache is not None and self.gateway is not None and self.gateway.cache_enabled:
            settings = self.gateway.settings
            identity = {
                "version": "chunk-discovery-v2",
                "prompt": prompt,
                "schema": ChunkDiscovery.model_json_schema(),
                "chunk": chunk.model_dump(mode="json"),
                "provider": settings.provider.value,
                "model": settings.model_for("discovery"),
                "endpoint": settings.base_url,
                "privacy_mode": settings.privacy_mode.value,
                "temperature": settings.temperature,
                "discovery_thinking": settings.discovery_thinking,
            }
            # Only the hash is used as a filename. No API keys are persisted.
            cache_key = "chunk-discovery-" + sha256_bytes(json.dumps(identity, sort_keys=True).encode())
            cached = cache.get_model(cache_key, ChunkDiscovery)
            if cached is not None:
                self.gateway.record_cache_hit(stage="discovery", operation="ChunkDiscovery", request_metadata=metadata)
                return cached
        from .chunk_discovery_recovery import ChunkDiscoveryRecovery
        recovery = ChunkDiscoveryRecovery(self.gateway, cache, chunk, self._source_pages, ChunkDiscovery, cache_key)
        cached_recovery = recovery.cached_root()
        if cached_recovery is not None:
            return cached_recovery
        recovered = False
        if recovery.checkpoint() is not None:
            discovery = recovery.recover()
            recovered = True
        else:
            try:
                discovery = self.gateway.generate_structured(  # type: ignore[union-attr]
                    [{"role": "system", "content": prompt}, untrusted_document_message(chunk.text)],
                    ChunkDiscovery, stage="discovery", request_metadata=metadata,
                )
            except LLMStructuredOutputError as exc:
                if not exc.response.usage or exc.response.usage.finish_reason != "length":
                    raise
                recovery.mark_truncated(exc)
                try:
                    discovery = recovery.recover()
                    recovered = True
                except Exception as failure:
                    raise failure from exc
        if cache_key is not None and not recovered:
            cache.set_model(cache_key, discovery)
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
