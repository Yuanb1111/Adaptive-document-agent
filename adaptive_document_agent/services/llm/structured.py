"""Tolerant parsing for provider-generated structured responses."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


def repair_extra_null_fields(text: str, response_model: type[T]) -> tuple[T, list[list[str | int]]] | None:
    """Remove only schema-forbidden null placeholders, preserving every declared value."""
    try:
        validate_structured_text(text, response_model)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
    except (ValueError, TypeError):
        return None
    else:
        return None
    if not errors or any(e['type'] != 'extra_forbidden' or e.get('input') is not None for e in errors):
        return None
    try:
        # Ambiguous duplicate keys cannot be repaired by silently choosing one.
        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('Duplicate JSON key')
                value[key] = item
            return value

        value = json.loads(_json_candidates(text)[0], object_pairs_hook=unique_object)
        paths = [list(e['loc']) for e in errors]
        for path in paths:
            parent = value
            for key in path[:-1]:
                parent = parent[key]
            if not isinstance(parent, dict) or path[-1] not in parent or parent[path[-1]] is not None:
                return None
            del parent[path[-1]]
        return response_model.model_validate(value), paths
    except (ValueError, TypeError, KeyError, IndexError):
        return None


def preserves_json_content(original: str, repaired: str) -> bool:
    """Conservatively allow punctuation repairs, never new scalar content.

    Valid JSON must retain its exact structure and values. For malformed JSON,
    require the same ordered non-syntax characters and every repaired string's
    exact encoded contents in the original. Uncertain repairs fail closed.
    """
    before = _json_candidates(original)
    after = _json_candidates(repaired)
    if not before or not after:
        return False
    original, repaired = before[0], after[0]
    try:
        return json.dumps(json.loads(original), sort_keys=True) == json.dumps(json.loads(repaired), sort_keys=True)
    except json.JSONDecodeError:
        pass
    if re.sub(r'[\s{}\[\],:\"]', '', original) != re.sub(r'[\s{}\[\],:\"]', '', repaired):
        return False
    for token in re.finditer(r'"((?:[^"\\]|\\.)*)"', repaired):
        is_key = repaired[token.end():].lstrip().startswith(':')
        if (token.group(1) if is_key else token.group()) not in original:
            return False
    return True


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
