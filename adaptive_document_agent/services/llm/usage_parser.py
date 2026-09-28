"""Normalize provider counters without inferring tokens from response text."""

from typing import Any


def get_field(value: Any, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage_counters(raw) -> dict:
    source = get_field(raw, "usage")
    inputs = _count(get_field(source, "prompt_tokens", get_field(source, "input_tokens")))
    outputs = _count(get_field(source, "completion_tokens", get_field(source, "output_tokens")))
    input_details = get_field(source, "prompt_tokens_details", get_field(source, "input_tokens_details"))
    output_details = get_field(source, "completion_tokens_details", get_field(source, "output_tokens_details"))
    cached = _count(get_field(source, "prompt_cache_hit_tokens"))
    if cached is None:
        cached = _count(get_field(input_details, "cached_tokens"))
    missed = _count(get_field(source, "prompt_cache_miss_tokens"))
    if inputs is not None:
        if missed is None and cached is not None and cached <= inputs:
            missed = inputs - cached
        if cached is None and missed is not None and missed <= inputs:
            cached = inputs - missed
    return {"input_tokens": inputs, "output_tokens": outputs,
            "cached_input_tokens": cached, "uncached_input_tokens": missed,
            "reasoning_tokens": _count(get_field(output_details, "reasoning_tokens")),
            "total_tokens": _count(get_field(source, "total_tokens"))}
