"""Hierarchical document discovery through the provider-independent gateway."""

import re
from collections.abc import Callable

from pydantic import BaseModel, Field

from adaptive_document_agent.models import AnalysisPageRange, DocumentProfile, ParsedDocument
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.utils.chunking import DocumentChunk, semantic_chunks

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


class DocumentDiscovery:
    def __init__(self, gateway: LLMGateway | None = None, *, target_tokens: int = 6_000) -> None:
        self.gateway = gateway
        self.target_tokens = target_tokens

    def discover(
        self,
        document: ParsedDocument,
        *,
        analysis_focus: str | None = None,
        progress: Callable[[str], None] | None = None,
        routed_ranges: list[AnalysisPageRange] | None = None,
    ) -> DocumentProfile:
        notify = progress or (lambda _: None)
        chunks = semantic_chunks(document.pages, target_tokens=self.target_tokens)
        if not self.gateway:
            profile = self._deterministic_profile(document, chunks)
            profile.analysis_focus = analysis_focus.strip() if analysis_focus and analysis_focus.strip() else None
            return profile
        if routed_ranges is None and len(chunks) > 24:
            notify("Mapping the large document and selecting relevant sections")
            routed_ranges = self._route_large_document(document, analysis_focus)
        routed_ranges = routed_ranges or []
        if routed_ranges:
            chunks = self._select_chunks(chunks, routed_ranges)
        discoveries: list[ChunkDiscovery] = []
        for index, chunk in enumerate(chunks, start=1):
            notify(f"Understanding selected pages {chunk.start_page}-{chunk.end_page} ({index}/{len(chunks)})")
            discoveries.append(self._discover_chunk(chunk))
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
        profile.analysis_focus = analysis_focus.strip() if analysis_focus and analysis_focus.strip() else None
        profile.analysis_page_ranges = [(item.start_page, item.end_page) for item in routed_ranges]
        for item in routed_ranges:
            if item.title not in profile.important_sections:
                profile.important_sections.append(item.title)
        return profile

    def route(self, document: ParsedDocument, analysis_focus: str | None = None) -> list[AnalysisPageRange]:
        """Select a bounded scope that can be reviewed before deep analysis."""
        chunks = semantic_chunks(document.pages, target_tokens=self.target_tokens)
        if self.gateway and len(chunks) > 24:
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
        return output

    @staticmethod
    def _select_chunks(chunks: list[DocumentChunk], ranges: list[AnalysisPageRange], *, maximum: int = 32) -> list[DocumentChunk]:
        selected = [
            chunk
            for chunk in chunks
            if any(chunk.start_page <= item.end_page and chunk.end_page >= item.start_page for item in ranges)
        ]
        if selected:
            return selected[:maximum]
        if len(chunks) <= maximum:
            return chunks
        step = len(chunks) / maximum
        return [chunks[min(int(index * step), len(chunks) - 1)] for index in range(maximum)]

    def _discover_chunk(self, chunk: DocumentChunk) -> ChunkDiscovery:
        return self.gateway.generate_structured(  # type: ignore[union-attr]
            [
                {"role": "system", "content": load_prompt("document_discovery.txt")},
                untrusted_document_message(chunk.text),
            ],
            ChunkDiscovery,
            stage="discovery",
        )

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
