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


def review_compact(gateway, messages, schema, audit, *, cancelled=None, validate=None, coverage_pages=None):
    catalog, previous_quote_pairs = None, set()
    if coverage_pages is not None:
        from .summary_coverage_protocol import (coverage_review_messages, bind_coverage_paragraphs,
                                                invalid_visible_quote_pairs, quote_disagreements)
        messages, catalog = coverage_review_messages(messages, coverage_pages)
    original = list(messages)
    attempts = audit.setdefault('compact_review_attempts', [])
    for attempt in range(3 if catalog is not None else 2):
        if cancelled is not None and cancelled.is_set():
            raise CancelledError('Compact summary review cancelled')
        record = {'attempt': attempt + 1}
        attempts.append(record)
        try:
            response = gateway.generate_structured(messages, schema, stage='presentation',
                allow_repair=False, cancelled=cancelled)
            record['response'] = response.model_dump(mode='json')
            if catalog is not None:
                count = bind_coverage_paragraphs(response, catalog)
                if count:
                    record['visible_paragraph_binding'] = {'count': count, 'semantic_approval': False}
                    record['bound_response'] = response.model_dump(mode='json')
            if validate is not None:
                validate(response)
            if attempt == 1 and catalog is not None:
                disputed = quote_disagreements(response, previous_quote_pairs)
                if disputed:
                    record.update(status='quote_verdict_disagreement', disputed_meanings=[
                        dict(part_id=part, meaning_index=index) for part, index in disputed])
                    messages = original + [untrusted_document_message(json.dumps(record, ensure_ascii=False)),
                        {'role': 'user', 'content':
                         'The earlier review claimed these meanings were covered but cited SOURCE text instead of '
                         'VISIBLE text; the quote repair now claims they are absent. These are conflicting reviews '
                         'of unchanged paragraphs, not an authorized content edit. Perform one final independent '
                         'semantic check against bound_visible_paragraphs for the disputed pairs. Read all current '
                         'paragraphs in their actual language. Return all part verdicts. Choose paragraph_ids for '
                         'covered meanings. Keep covered=false if the meaning or a necessary qualification is truly '
                         'absent. Never infer coverage from author references or force acceptance to fix formatting.'}]
                    continue
            record['status'] = 'success'
            return response
        except (LLMStructuredOutputError, ReviewTargetError) as exc:
            if catalog is not None and isinstance(exc, ReviewTargetError):
                previous_quote_pairs = invalid_visible_quote_pairs(response, catalog)
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
