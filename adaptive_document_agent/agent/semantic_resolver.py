"""Conservative metric, period, and unit semantic resolution."""

import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from adaptive_document_agent.models.entity import SemanticMapping
from adaptive_document_agent.services.llm import LLMGateway

from .prompting import load_prompt, untrusted_document_message


class SemanticResolution(BaseModel):
    mappings: list[SemanticMapping] = Field(default_factory=list)


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
        if workers > 1 and len(unique) > 48:
            # Every request sees the complete vocabulary and the same evidence
            # context, but emits mappings only for its assigned terms. Bound
            # both concurrency and response size without dropping any terms.
            batches = [unique[start:start + 48] for start in range(0, len(unique), 48)]
            vocabulary = "\n".join(unique)
            with ThreadPoolExecutor(max_workers=min(workers, len(batches)), thread_name_prefix="semantic") as pool:
                responses = list(pool.map(
                    lambda batch: self._resolve_batch(batch, context=context, vocabulary=vocabulary), batches,
                ))
            return [mapping for response in responses for mapping in response]
        return self._resolve_batch(unique, context=context)

    def _resolve_batch(self, unique: list[str], *, context: str, vocabulary: str = "") -> list[SemanticMapping]:
        payload = "Metric names:\n" + "\n".join(f"- {name}" for name in unique) + "\nContext:\n" + context[:12_000]
        if vocabulary:
            payload += "\nComplete document metric vocabulary (reference only):\n" + vocabulary
        response = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("semantic_resolution.txt") + (
                    "\nReturn mappings only for the assigned Metric names. Use the complete vocabulary "
                    "to distinguish related terms; do not merge distinct meanings. Keep reasons concise."
                    if vocabulary else ""
                )},
                untrusted_document_message(payload),
            ],
            SemanticResolution,
            stage="semantic",
        )
        by_original = {mapping.original_name: mapping for mapping in response.mappings}
        return [by_original.get(name, SemanticMapping(original_name=name, confidence=0.0, reason="Model omitted this term.")) for name in unique]

    @staticmethod
    def normalize_period(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = " ".join(value.strip().split())
        match = re.fullmatch(r"(?i)(?:FY\s*)?((?:19|20)\d{2})", cleaned)
        return match.group(1) if match else cleaned
