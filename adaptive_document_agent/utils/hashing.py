"""Content hashing helpers."""

import hashlib


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

