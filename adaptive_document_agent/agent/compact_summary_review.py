"""Repair the review protocol once without regenerating validated slide copy."""
import json
from concurrent.futures import CancelledError

from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .prompting import untrusted_document_message


class CompactReviewProtocolError(ValueError):
    """The bounded reviewer returned no usable verdict; editing cannot fix it."""


def review_compact(gateway, messages, schema, audit, *, cancelled=None):
    original = list(messages)
    attempts = audit.setdefault('compact_review_attempts', [])
    for attempt in range(2):
        if cancelled is not None and cancelled.is_set():
            raise CancelledError('Compact summary review cancelled')
        record = {'attempt': attempt + 1}
        attempts.append(record)
        try:
            response = gateway.generate_structured(messages, schema, stage='presentation',
                allow_repair=False, cancelled=cancelled)
            record['status'] = 'success'
            return response
        except LLMStructuredOutputError as exc:
            record.update(status='invalid_format', raw_response=exc.response.text,
                          validation_detail=str(exc.__cause__ or exc))
            truncated = bool(exc.response.usage and exc.response.usage.finish_reason == 'length')
            if attempt or truncated:
                raise CompactReviewProtocolError('Compact semantic review protocol failed: '
                    + record['validation_detail']) from exc
            messages = original + [untrusted_document_message(json.dumps(record, ensure_ascii=False)),
                {'role': 'user', 'content':
                 'Repair only the review response using the SAME supplied source and SAME pages. '
                 'Return every exact part ID once and explicit opening/identity verdicts. '
                 'Keep reasons concise within the schema limits. Never turn a rejection into acceptance '
                 'to fix formatting. Do not rewrite the introduction or invent missing evidence.'}]
