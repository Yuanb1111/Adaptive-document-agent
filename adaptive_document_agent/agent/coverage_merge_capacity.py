"""Bound merge output capacity using its complete immutable response inventory."""

import json


MAX_MERGE_OUTPUT_TOKENS = 32_768


def merge_output_tokens(selection, decisions, *, base_tokens=8192):
    """Reserve response headroom without assuming a provider tokenizer.

    A merge repeats accepted topics and decides every proposed addition. The
    ordinary delta budget cannot accommodate an arbitrarily larger inventory.
    UTF-8 bytes provide a conservative sizing signal, not a token guarantee:
    allow five tokens per eight bytes plus 1,024 tokens of synthesis headroom.
    Keep ordinary small responses unchanged and an explicit absolute ceiling.
    Truncation still fails through the gateway; no missing decision is accepted.
    """
    if not 1 <= base_tokens <= MAX_MERGE_OUTPUT_TOKENS:
        raise ValueError('Merge base token budget must fit the bounded output ceiling.')
    inventory = {**selection, 'coverage_decisions': decisions}
    size = len(json.dumps(inventory, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    capacity = (size * 5 + 7) // 8 + 1024
    return max(base_tokens, min(MAX_MERGE_OUTPUT_TOKENS, capacity))
