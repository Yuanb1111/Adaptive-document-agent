"""Repair the review protocol once without regenerating validated slide copy."""
import json
from concurrent.futures import CancelledError

from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .prompting import untrusted_document_message


class CompactReviewProtocolError(ValueError):
    """The bounded reviewer returned no usable verdict; editing cannot fix it."""


class ReviewTargetError(ValueError):
    """A verdict was not bound to the supplied generated slide/evidence IDs."""


def validate_review_target(response, pages, part_ids, require_opening):
    if len(response.parts) != len(part_ids) or {p.part_id for p in response.parts} != part_ids:
        raise ReviewTargetError('Review must cover every exact content part ID once')
    if require_opening and (response.opening_slide_id != pages[0].id or
            response.opening_item_texts != [item.text for item in pages[0].items]):
        raise ReviewTargetError('Opening verdict targets the wrong or incomplete slide. Copy opening_target '
            'slide_id and ALL item_texts exactly, in order. Judge those generated paragraphs, not PDF cover pages.')


def review_compact(gateway, messages, schema, audit, *, cancelled=None, validate=None):
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
            record['response'] = response.model_dump(mode='json')
            if validate is not None:
                validate(response)
            record['status'] = 'success'
            return response
        except (LLMStructuredOutputError, ReviewTargetError) as exc:
            record.update(status='invalid_target' if isinstance(exc, ReviewTargetError) else 'invalid_format',
                          raw_response=exc.response.text if isinstance(exc, LLMStructuredOutputError) else None,
                          validation_detail=str(exc.__cause__ or exc))
            truncated = isinstance(exc, LLMStructuredOutputError) and bool(
                exc.response.usage and exc.response.usage.finish_reason == 'length')
            if attempt or truncated:
                raise CompactReviewProtocolError('Compact semantic review protocol failed: '
                    + record['validation_detail']) from exc
            messages = original + [untrusted_document_message(json.dumps(record, ensure_ascii=False)),
                {'role': 'user', 'content':
                 'Repair only the review response using the SAME supplied source and SAME pages. '
                 'Return every exact part ID once and explicit opening/identity verdicts. '
                 'Bind the opening verdict to opening_target.slide_id and its exact ordered item_texts. '
                 'PDF identity evidence is only for identity checking; it is never the generated opening. '
                 'Keep reasons concise within the schema limits. Never turn a rejection into acceptance '
                 'to fix formatting. Do not rewrite the introduction or invent missing evidence.'}]
