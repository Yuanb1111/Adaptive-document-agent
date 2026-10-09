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
    if candidates:
        # A schema failure belongs to the outer response. Never accept an inner
        # fact as the whole answer, or replace the useful error with the last
        # nested object's missing fields (which sends repairs in the wrong direction).
        return response_model.model_validate_json(candidates[0])
    raise ValueError("The model response did not contain a JSON object or array.")


def _json_candidates(text: str) -> list[str]:
    clean = text.strip().lstrip("\ufeff")
    decoder = json.JSONDecoder()
    if clean.startswith(('{', '[')):
        try:
            _, end = decoder.raw_decode(clean)
        except json.JSONDecodeError:
            return [clean]
        return [clean[:end]]
    # Prefer the complete fenced response over braces in its prose preamble.
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", clean, flags=re.IGNORECASE)
    if fence:
        return [fence.group(1).strip()]
    for position, character in enumerate(clean):
        if character not in "{[":
            continue
        try:
            _, end = decoder.raw_decode(clean[position:])
        except json.JSONDecodeError:
            return [clean[position:]]  # wrapped malformed root must not expose nested answers
        return [clean[position:position + end]]
    return []
