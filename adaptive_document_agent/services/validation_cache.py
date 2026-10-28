"""Bounded, invocation-local reuse of deterministic validation work only."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
import json
from threading import get_ident

_active = ContextVar('deterministic_validation_cache', default=None)
MAX_TEXT_CHARS = 32_000
MAX_TEXT_ENTRIES = 512
MAX_TOTAL_TEXT_CHARS = 4_000_000


def _current():
    cache = _active.get()
    return cache if cache is not None and cache['owner'] == get_ident() else None


@contextmanager
def validation_cache_scope():
    """Nested readers share work; no cache survives an analysis/export call."""
    if _current() is not None:
        yield
        return
    cache = {'owner': get_ident(), 'text': OrderedDict(), 'chars': 0,
             'audit': OrderedDict(), 'ranking': OrderedDict()}
    token = _active.set(cache)
    try:
        yield
    finally:
        _active.reset(token)
        cache['text'].clear()
        cache['audit'].clear()
        cache['ranking'].clear()


def normalized_quote(text, compute):
    cache = _current()
    if cache is None or len(text) > MAX_TEXT_CHARS:
        return compute(text)
    entries = cache['text']
    if text in entries:
        entries.move_to_end(text)
        return entries[text]
    value = compute(text)
    size = len(text) + len(value)
    entries[text] = value
    cache['chars'] += size
    while len(entries) > MAX_TEXT_ENTRIES or cache['chars'] > MAX_TOTAL_TEXT_CHARS:
        old, normalized = entries.popitem(last=False)
        cache['chars'] -= len(old) + len(normalized)
    return value


def accepted_audit_record(result, issue, verify):
    """Fingerprint ALL source inputs, never IDs or mutable object identity.

    Full document text, geometry, tables, navigation, profile/source checks,
    observations and the latest audit event determine acceptance. Final target
    membership is still checked separately by require_report_audit_scope.
    """
    cache = _current()
    if cache is None:
        return verify(result, issue)
    digest = sha256(result.model_dump_json(
        include={'document', 'profile', 'observations'}).encode('utf-8'))
    digest.update(issue.model_dump_json().encode('utf-8'))
    key = digest.digest()
    entries = cache['audit']
    if key in entries:
        entries.move_to_end(key)
        return deepcopy(entries[key])
    value = verify(result, issue)
    entries[key] = deepcopy(value)  # Callers cannot mutate a cached approval.
    if len(entries) > 8:
        entries.popitem(last=False)
    return value


def ranked_profile_pages(document, profile, max_pages, rank):
    """Reuse retrieval scores only while every ranking input is unchanged."""
    cache = _current()
    if cache is None:
        return rank(document, profile, max_pages)
    # Keep only a digest and page numbers, not another copy of the source text.
    inputs = [document.page_count, [(p.page_number, p.text) for p in document.pages],
              profile.document_summary_pages if profile else [], max_pages]
    key = (rank.__self__, sha256(json.dumps(inputs, ensure_ascii=False).encode('utf-8')).digest())
    entries = cache['ranking']
    if key in entries:
        entries.move_to_end(key)
        return list(entries[key])
    pages = rank(document, profile, max_pages)
    entries[key] = tuple(pages)
    if len(entries) > 8:
        entries.popitem(last=False)
    return pages
