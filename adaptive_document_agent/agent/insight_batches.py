"""Generate complete insight batches, splitting only truncated requests."""

import json
from collections.abc import Iterator

from adaptive_document_agent.models import Insight
from adaptive_document_agent.services.llm import LLMGateway
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.utils.ids import stable_id

from .prompting import untrusted_document_message


MAX_RESULTS = 6
MAX_PAYLOAD_CHARS = 32_000


def _batches(records: list[dict]) -> Iterator[list[dict]]:
    """Keep each calculation and its source context intact, including large ones."""
    batch, size = [], 2
    for record in records:
        length = len(json.dumps(record, ensure_ascii=False))
        if batch and (len(batch) >= MAX_RESULTS or size + length + 2 > MAX_PAYLOAD_CHARS):
            yield batch
            batch, size = [], 2
        batch.append(record)
        size += length + (2 if len(batch) > 1 else 0)
    if batch:
        yield batch


def generate_batches(gateway: LLMGateway, records: list[dict], schema: type,
                     prompt: str) -> Iterator[tuple[list[str], list[Insight]]]:
    """Reuse successful gateway cache entries; never salvage partial JSON.

    A length failure bisects only its complete result records. A singleton is
    the recovery boundary: surface its failure rather than loop, drop evidence,
    switch providers, or substitute unsupported prose.
    """
    instructions = (prompt + "\nThis request is one bounded batch. Return at most one insight per supplied "
                    "result, merging related results when useful. Use unique insight IDs containing linked "
                    "task IDs. Keep evidence empty in the output: Python attaches the validated source "
                    "evidence. Cite supported drivers using driver_quote and driver_source_page. "
                    "Do not repeat source_context, input_observations or result dictionaries in the output. "
                    "Retain essential scope and caveats; optional unsupported fields must be null.")

    def request(batch: list[dict], depth: int = 0):
        ids = [record["task_id"] for record in batch]
        try:
            generated = gateway.generate_structured(
                [{"role": "system", "content": instructions},
                 untrusted_document_message(json.dumps(batch, ensure_ascii=False))],
                schema, stage="insight", request_metadata={
                    "chunk_id": stable_id("insight-batch", *ids), "recovery_depth": depth,
                },
            ).insights
        except LLMStructuredOutputError as exc:
            if not exc.response.usage or exc.response.usage.finish_reason != "length":
                raise
            if len(batch) == 1:
                raise LLMStructuredOutputError(
                    f"{exc} Insight generation still exceeded the output limit for one complete "
                    f"result ({ids[0]}); batch recovery cannot split its evidence further.",
                    response=exc.response,
                ) from exc
            midpoint = len(batch) // 2
            yield from request(batch[:midpoint], depth + 1)
            yield from request(batch[midpoint:], depth + 1)
            return
        yield ids, generated

    for batch in _batches(records):
        yield from request(batch)
