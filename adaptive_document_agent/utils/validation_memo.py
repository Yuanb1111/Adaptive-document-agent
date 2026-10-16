"""Bounded content-addressed reuse of deterministic checks, never model approval."""
from collections import OrderedDict
from hashlib import sha256
from threading import Lock


class ValidationMemo:
    """Retain only input digests and immutable diagnostics, not document contents."""

    def __init__(self, capacity=16):
        self.capacity = capacity
        self._values = OrderedDict()
        self._lock = Lock()

    def check(self, inputs, validate):
        digest = sha256()
        for encoded in inputs:
            value = encoded.encode('utf-8')
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
        key = digest.digest()
        with self._lock:
            if key in self._values:
                self._values.move_to_end(key)
                return list(self._values[key])
        errors = tuple(validate())
        with self._lock:
            self._values[key] = errors
            self._values.move_to_end(key)
            while len(self._values) > self.capacity:
                self._values.popitem(last=False)
        return list(errors)
