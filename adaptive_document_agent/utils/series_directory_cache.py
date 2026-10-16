"""Bound complete deterministic series directories without retaining source objects."""
from collections import OrderedDict
from hashlib import sha256
import json
from threading import Lock


class SeriesDirectoryCache:
    """Cache pure directory data and ordered IDs; rebind every current snapshot."""

    def __init__(self, capacity=4):
        if type(capacity) is not int or not 1 <= capacity <= 4:
            raise ValueError('Series directory cache capacity must be between one and four')
        self.capacity = capacity
        self._values = OrderedDict()
        self._lock = Lock()

    def directory(self, result, build):
        observations = {item.id: item for item in result.observations}
        if len(observations) != len(result.observations):
            # IDs cannot address distinct duplicate records. Preserve the
            # original builder's behavior rather than silently merging them.
            return build(result)
        digest = sha256()
        def add(encoded):
            value = encoded.encode('utf-8')
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
        # Ratio definitions, category scope, ambiguity and row qualifications
        # use complete source text/tables/geometry; identity labels alone are
        # insufficient. Preserve observation order and every retained field.
        add(result.document.model_dump_json())
        for item in result.observations:
            add(item.model_dump_json())
        key = digest.digest()
        with self._lock:
            cached = self._values.get(key)
            if cached is not None:
                self._values.move_to_end(key)
        if cached is not None:
            data, series_ids = cached
            return json.loads(data), {sid: [observations[oid] for oid in ids] for sid, ids in series_ids}
        directory, lookup = build(result)
        if any(observations.get(item.id) is not item for group in lookup.values() for item in group):
            # A future projection may return derived observation copies. An ID
            # cannot encode that projection, so never cache it as a raw lookup.
            return directory, lookup
        stored = (json.dumps(directory, ensure_ascii=False, separators=(',', ':')),
                  tuple((sid, tuple(item.id for item in group)) for sid, group in lookup.items()))
        with self._lock:
            self._values[key] = stored
            self._values.move_to_end(key)
            while len(self._values) > self.capacity:
                self._values.popitem(last=False)
        return directory, lookup
