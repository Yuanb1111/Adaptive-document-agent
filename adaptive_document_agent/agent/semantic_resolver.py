"""Conservative metric, period, and unit semantic resolution."""

import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from adaptive_document_agent.models.entity import SemanticMapping
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError

from .prompting import load_prompt, untrusted_document_message


class SemanticResolution(BaseModel):
    mappings: list[SemanticMapping] = Field(default_factory=list)


class SemanticResolutionRecovery(SemanticResolution):
    """Smaller conservative assignment after an output-limit failure."""


class SemanticResolver:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway

    def resolve_metrics(self, names: list[str], *, context: str = "") -> list[SemanticMapping]:
        unique = list(dict.fromkeys(name.strip() for name in names if name.strip()))
        if not unique:
            return []
        if not self.gateway:
            return [SemanticMapping(original_name=name, canonical_name=None, confidence=0.5, reason="No semantic model configured; original preserved.") for name in unique]
        workers = getattr(self.gateway, "discovery_workers", 1)
        batch_size = self.gateway.settings.semantic_batch_size if isinstance(self.gateway, LLMGateway) else 96
        if workers > 1 and len(unique) > batch_size:
            # Every request sees the complete vocabulary and the same evidence
            # context, but emits mappings only for its assigned terms. Bound
            # both concurrency and response size without dropping any terms.
            batches = [unique[start:start + batch_size] for start in range(0, len(unique), batch_size)]
            vocabulary = "\n".join(unique)
            with ThreadPoolExecutor(max_workers=min(workers, len(batches)), thread_name_prefix="semantic") as pool:
                responses = list(pool.map(
                    lambda batch: self._resolve_batch(batch, context=context, vocabulary=vocabulary), batches,
                ))
            return [mapping for response in responses for mapping in response]
        return self._resolve_batch(unique, context=context)

    def _resolve_batch(self, unique: list[str], *, context: str, vocabulary: str = "",
                       split_depth: int = 0) -> list[SemanticMapping]:
        try:
            return self._request_batch(unique, context=context, vocabulary=vocabulary,
                                       recovery=split_depth > 0)
        except LLMStructuredOutputError as exc:
            # Truncated reasoning/output cannot be repaired as JSON. Retry a
            # smaller assignment, preserving all terms and the shared context.
            # Never turn provider, privacy or ordinary schema errors into splits.
            usage = exc.response.usage
            if not usage or usage.finish_reason != 'length' or len(unique) < 2 or split_depth >= 2:
                raise
            middle = len(unique) // 2
            shared = vocabulary or "\n".join(unique)
            return [mapping for batch in (unique[:middle], unique[middle:])
                    for mapping in self._resolve_batch(batch, context=context, vocabulary=shared,
                                                       split_depth=split_depth + 1)]

    def _request_batch(self, unique: list[str], *, context: str, vocabulary: str,
                       recovery: bool = False) -> list[SemanticMapping]:
        # Stable shared prefix before the changing batch lets provider prefix
        # caching reuse the context. Every batch still sees all source terms.
        payload = "Context:\n" + context[:12_000]
        if vocabulary:
            payload += "\nComplete document metric vocabulary (reference only):\n" + vocabulary
        payload += "\nMetric names:\n" + "\n".join(f"- {name}" for name in unique)
        response = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("semantic_resolution.txt") + (
                    "\nReturn mappings only for the assigned Metric names. Use the complete vocabulary "
                    "to distinguish related terms; do not merge distinct meanings. Reasons: at most one short sentence. "
                    "Do not repeat source context or the whole vocabulary in your answer."
                    if vocabulary else ""
                )},
                untrusted_document_message(payload),
            ],
            SemanticResolutionRecovery if recovery else SemanticResolution,
            stage="semantic",
        )
        by_original = {mapping.original_name: mapping for mapping in response.mappings}
        # A shared unit cannot erase an explicit source measure qualifier.
        # Retain uncertainty rather than deciding a replacement semantic name.
        for name, mapping in list(by_original.items()):
            source = name.casefold()
            canonical = (mapping.canonical_name or '').casefold()
            capacity = ('capacity', '产能', '產能')
            actual = ('actual production', 'production volume', 'production output', '产量', '產量')
            if canonical and (
                    any(term in source for term in capacity) and not any(term in canonical for term in capacity)
                    or any(term.replace(' ', '') in source.replace(' ', '') for term in actual)
                    and any(term in canonical for term in capacity)):
                by_original[name] = mapping.model_copy(update={'canonical_name': None,
                    'reason': 'Canonical mapping loses or changes an explicit source measure qualifier; original retained.'})
        return [by_original.get(name, SemanticMapping(original_name=name, confidence=0.0, reason="Model omitted this term.")) for name in unique]

    @staticmethod
    def normalize_period(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = " ".join(value.strip().split())
        match = re.fullmatch(r"(?i)(?:FY\s*)?((?:19|20)\d{2})", cleaned)
        return match.group(1) if match else cleaned
