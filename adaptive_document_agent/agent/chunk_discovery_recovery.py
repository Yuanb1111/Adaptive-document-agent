"""Bounded, source-preserving recovery of truncated discovery inventories."""

import json
import re
from dataclasses import asdict, dataclass, replace
from typing import Literal

from pydantic import BaseModel

from adaptive_document_agent.models.page import DocumentPage
from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMStructuredOutputError
from adaptive_document_agent.utils.chunking import DocumentChunk
from adaptive_document_agent.utils.hashing import sha256_bytes
from adaptive_document_agent.utils.ids import stable_id

from .prompting import load_prompt, untrusted_document_message

MAX_RECOVERY_REQUESTS = 6
MAX_RECOVERY_DEPTH = 2
RECOVERY_POLICY = "chunk-discovery-recovery-v1"


@dataclass(frozen=True)
class SourceSlice:
    source_page_start: int
    source_page_end: int
    text: str
    source_char_start: int = 0


@dataclass(frozen=True)
class DiscoveryFragment:
    chunk_id: str
    slices: tuple[SourceSlice, ...]

    @property
    def start_page(self) -> int:
        return self.slices[0].source_page_start

    @property
    def end_page(self) -> int:
        return self.slices[-1].source_page_end


class SplitCheckpoint(BaseModel):
    """Only failure routing metadata; never a partial discovery result."""

    split_required: Literal[True] = True
    output_tokens: int | None = None


def source_fragment(chunk: DocumentChunk, pages: list[DocumentPage]) -> DiscoveryFragment:
    """Use trusted page objects only when they exactly reproduce this chunk.

    Standalone/custom chunks keep their original page range on each fragment.
    Page-like strings inside PDF text never assign or override provenance.
    """
    selected = [page for page in pages if chunk.start_page <= page.page_number <= chunk.end_page]
    rebuilt = "\n\n".join(f"[PAGE {page.page_number}]\n{page.text}" for page in selected)
    if selected and rebuilt == chunk.text:
        slices = tuple(SourceSlice(page.page_number, page.page_number, page.text) for page in selected)
    else:
        slices = (SourceSlice(chunk.start_page, chunk.end_page, chunk.text),)
    return DiscoveryFragment(chunk.chunk_id, slices)


def split_fragment(fragment: DiscoveryFragment) -> tuple[DiscoveryFragment, DiscoveryFragment] | None:
    """Bisect on whole pages, then paragraphs/lines/sentences/word boundaries."""
    slices = fragment.slices
    if len(slices) > 1:
        lengths = [max(1, len(item.text)) for item in slices]
        total = sum(lengths)
        split = min(range(1, len(slices)), key=lambda index: abs(sum(lengths[:index]) * 2 - total))
        halves = (slices[:split], slices[split:])
    else:
        item = slices[0]
        text = item.text
        boundary = None
        fallback = None
        first_content = len(text) - len(text.lstrip())
        last_content = len(text.rstrip())
        for pattern in (r"(?:\r?\n){2,}", r"\r\n|\r|\n", r"[。！？；;]", r"\s+"):
            candidates = [match.end() for match in re.finditer(pattern, text)
                          if first_content < match.end() < last_content]
            if candidates:
                nearest = min(candidates, key=lambda point: abs(point * 2 - len(text)))
                if len(text) / 4 <= nearest <= len(text) * 3 / 4:
                    boundary = nearest
                    break
                if fallback is None or abs(nearest * 2 - len(text)) < abs(fallback * 2 - len(text)):
                    fallback = nearest
        boundary = boundary if boundary is not None else fallback
        if boundary is None:
            return None
        halves = (
            (replace(item, text=text[:boundary]),),
            (replace(item, text=text[boundary:], source_char_start=item.source_char_start + boundary),),
        )
    return tuple(DiscoveryFragment(
        stable_id("discovery_fragment", fragment.chunk_id, index,
                  json.dumps([asdict(item) for item in half], ensure_ascii=False, sort_keys=True)), half,
    ) for index, half in enumerate(halves, 1))


class ChunkDiscoveryRecovery:
    """Share one request/depth budget across every descendant of a failed chunk."""

    def __init__(self, gateway, cache, chunk: DocumentChunk, pages: list[DocumentPage], response_model: type[BaseModel], parent_cache_key: str | None):
        self.gateway = gateway
        self.cache = cache if getattr(gateway, "cache_enabled", False) else None
        self.response_model = response_model
        self.root = source_fragment(chunk, pages)
        self.requests = 0
        self._truncations: dict[str, SplitCheckpoint] = {}
        self._splits = {}
        self.prompt = load_prompt("chunk_discovery.txt") + "\n" + load_prompt("chunk_discovery_recovery.txt")
        identity = {"policy": RECOVERY_POLICY, "max_requests": MAX_RECOVERY_REQUESTS,
                    "max_depth": MAX_RECOVERY_DEPTH, "prompt": self.prompt,
                    "schema": response_model.model_json_schema(), "parent_cache_key": parent_cache_key,
                    "source": [asdict(item) for item in self.root.slices]}
        if self.cache is not None:
            settings = gateway.settings
            identity.update(provider=settings.provider.value, model=settings.model_for("discovery"),
                            endpoint=settings.base_url, privacy=settings.privacy_mode.value,
                            temperature=settings.temperature, discovery_thinking=settings.discovery_thinking)
        self.key = "chunk-recovery-" + sha256_bytes(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def _key(self, fragment: DiscoveryFragment, kind: str) -> str:
        return f"{self.key}-{kind}-{fragment.chunk_id}"

    def checkpoint(self, fragment: DiscoveryFragment | None = None) -> SplitCheckpoint | None:
        return self.cache.get_model(self._key(fragment or self.root, "split"), SplitCheckpoint) if self.cache is not None else None

    def cached_root(self):
        value = self.cache.get_model(self._key(self.root, "result"), self.response_model) if self.cache is not None else None
        if value is not None:
            self.gateway.record_cache_hit(stage="discovery", operation="ChunkDiscovery", request_metadata={
                "chunk_id": self.root.chunk_id, "source_page_start": self.root.start_page,
                "source_page_end": self.root.end_page,
            })
        return value

    def _children(self, fragment: DiscoveryFragment):
        if fragment.chunk_id not in self._splits:
            self._splits[fragment.chunk_id] = split_fragment(fragment)
        return self._splits[fragment.chunk_id]

    def mark_truncated(self, error: LLMStructuredOutputError, fragment: DiscoveryFragment | None = None, *, depth: int = 0) -> None:
        fragment = fragment or self.root
        usage = error.response.usage
        checkpoint = SplitCheckpoint(output_tokens=usage.output_tokens if usage else None)
        self._truncations[fragment.chunk_id] = checkpoint
        # A terminal failed leaf is not permanently poisoned. A later explicit
        # retry may request that leaf again while reusing successful siblings.
        if self.cache is not None and depth < MAX_RECOVERY_DEPTH and self._children(fragment) is not None:
            self.cache.set_model(self._key(fragment, "split"), checkpoint)

    def recover(self):
        return self._split_and_recover(self.root, depth=0)

    def _failure(self, fragment: DiscoveryFragment, reason: str):
        checkpoint = self._truncations.get(fragment.chunk_id) or self.checkpoint(fragment)
        tokens = f" Last truncated output: {checkpoint.output_tokens} tokens." if checkpoint and checkpoint.output_tokens is not None else ""
        raise LLMResponseError(
            f"Discovery ChunkDiscovery recovery could not complete for source pages {fragment.start_page}-{fragment.end_page}: "
            f"{reason} (maximum {MAX_RECOVERY_REQUESTS} recovery requests, depth {MAX_RECOVERY_DEPTH}). "
            "No partial inventory was accepted. Narrow the selected evidence scope or use a model with sufficient output capacity."
            + tokens)

    def _split_and_recover(self, fragment: DiscoveryFragment, *, depth: int):
        if depth >= MAX_RECOVERY_DEPTH:
            self._failure(fragment, "the bounded split depth was reached")
        children = self._children(fragment)
        if children is None:
            self._failure(fragment, "the source has no safe smaller text boundary")
        results = [self._resolve(child, depth=depth + 1, parent_id=fragment.chunk_id, index=index)
                   for index, child in enumerate(children, 1)]
        merged = {"summary": "\n\n".join(
            f"[SOURCE PAGES {child.start_page}-{child.end_page}] {result.summary}"
            for child, result in zip(children, results, strict=True))}
        for field in self.response_model.model_fields:
            if field != "summary":
                merged[field] = list(dict.fromkeys(value for result in results for value in getattr(result, field)))
        value = self.response_model.model_validate(merged)
        if self.cache is not None:
            self.cache.set_model(self._key(fragment, "result"), value)
        return value

    def _resolve(self, fragment: DiscoveryFragment, *, depth: int, parent_id: str, index: int):
        metadata = {"chunk_id": fragment.chunk_id, "source_page_start": fragment.start_page,
                    "source_page_end": fragment.end_page, "parent_chunk_id": parent_id,
                    "fragment_index": index, "fragment_count": 2, "recovery_depth": depth}
        if self.cache is not None:
            cached = self.cache.get_model(self._key(fragment, "result"), self.response_model)
            if cached is not None:
                self.gateway.record_cache_hit(stage="discovery", operation="ChunkDiscovery", request_metadata=metadata)
                return cached
        if self.checkpoint(fragment) is not None:
            return self._split_and_recover(fragment, depth=depth)
        if self.requests >= MAX_RECOVERY_REQUESTS:
            self._failure(fragment, "the shared recovery request budget was reached")
        self.requests += 1
        payload = {"source_fragments": [asdict(item) for item in fragment.slices]}
        try:
            value = self.gateway.generate_structured(
                [{"role": "system", "content": self.prompt},
                 untrusted_document_message(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))],
                self.response_model, stage="discovery", allow_repair=False, request_metadata=metadata,
            )
        except LLMStructuredOutputError as exc:
            if not exc.response.usage or exc.response.usage.finish_reason != "length":
                raise
            self.mark_truncated(exc, fragment, depth=depth)
            try:
                return self._split_and_recover(fragment, depth=depth)
            except LLMResponseError as failure:
                raise failure from exc
        if self.cache is not None:
            self.cache.set_model(self._key(fragment, "result"), value)
        return value
