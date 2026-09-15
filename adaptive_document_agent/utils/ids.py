"""Safe deterministic internal identifiers."""

import hashlib


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8", errors="replace")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:16]}"

