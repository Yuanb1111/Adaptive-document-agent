"""Conservative metric, period, and unit semantic resolution."""

import re

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
        if not self.gateway:
            return [SemanticMapping(original_name=name, canonical_name=None, confidence=0.5, reason="No semantic model configured; original preserved.") for name in unique]
        payload = "Metric names:\n" + "\n".join(f"- {name}" for name in unique) + "\nContext:\n" + context[:12_000]
        response = self.gateway.generate_structured(
            [
                {"role": "system", "content": load_prompt("semantic_resolution.txt")},
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

