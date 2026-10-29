"""Recover review capacity without sampling facts or accepting partial JSON."""
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError

from .presentation_budget_output import complete_budget_output

REVIEW_TOKEN_LIMITS = (16384, 24576)
MAX_TOPICS_PER_BATCH = 3
MAX_REVIEW_CALLS = 24


def is_truncated(error):
    return (isinstance(error, LLMStructuredOutputError) and error.response.usage is not None
            and error.response.usage.finish_reason == 'length')


def review_batches(topics, *, payload, request, characters, record, on_failure):
    """Bisect complete topics on capacity failures; preserve successful siblings.

    A topic is indivisible: its complete facts and current draft travel together.
    Invalid JSON, transport failure and semantic rejection are not truncation.
    The caller owns the global physical-call budget and privacy propagation.
    """
    import json
    from adaptive_document_agent.services.llm.exceptions import LLMResponseError, LLMTransportError

    def run(batch):
        encoded = json.dumps(payload(batch), ensure_ascii=False, separators=(',', ':'))
        if len(encoded) > characters:
            if len(batch) == 1:
                on_failure(batch, 'Complete topic evidence exceeds the review context capacity; no facts sampled.')
                return {}
            middle = len(batch) // 2
            return {**run(batch[:middle]), **run(batch[middle:])}
        try:
            return request(batch)
        except (LLMResponseError, LLMTransportError, ValueError) as exc:
            if is_truncated(exc) and len(batch) > 1:
                record.setdefault('capacity_splits', []).append([t.id for t in batch])
                middle = len(batch) // 2
                return {**run(batch[:middle]), **run(batch[middle:])}
            on_failure(batch, str(exc))
            return {}

    decisions = {}
    for offset in range(0, len(topics), MAX_TOPICS_PER_BATCH):
        decisions.update(run(topics[offset:offset + MAX_TOPICS_PER_BATCH]))
    return decisions


def review_request(gateway, messages, schema, record, budget, *, lock=None, cancelled=None):
    from contextlib import nullcontext
    from concurrent.futures import CancelledError

    def reserve():
        with lock if lock is not None else nullcontext():
            if cancelled is not None and cancelled.is_set():
                raise CancelledError('Topic evidence review cancelled')
            if budget['calls'] >= MAX_REVIEW_CALLS:
                raise ValueError('Topic semantic review call budget exhausted; remaining topics are unreviewed.')
            budget['calls'] += 1
    return complete_budget_output(gateway, messages, schema, record,
        audit_key='output_attempts', token_limits=REVIEW_TOKEN_LIMITS, before_attempt=reserve,
        cancelled=cancelled)
