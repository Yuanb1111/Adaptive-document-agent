"""Tolerant parsing for provider-generated structured responses."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


def validate_structured_text(text: str, response_model: type[T]) -> T:
    """Validate exact JSON or one JSON value wrapped in harmless model prose."""
    candidates = _json_candidates(text)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return response_model.model_validate_json(candidate)
        except (ValueError, TypeError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("The model response did not contain a JSON object or array.")


def _json_candidates(text: str) -> list[str]:
    clean = text.strip().lstrip("\ufeff")
    candidates: list[str] = []
    if clean:
        candidates.append(clean)
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", clean, flags=re.IGNORECASE)
        if match.group(1).strip()
    )

    decoder = json.JSONDecoder()
    for position, character in enumerate(clean):
        if character not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(clean[position:])
        except json.JSONDecodeError:
            continue
        candidates.append(clean[position:position + end])

    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            output.append(candidate)
    return output
