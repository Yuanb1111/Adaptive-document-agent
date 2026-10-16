"""Repair draft serialization without spending a content-revision attempt."""
import json
from concurrent.futures import CancelledError
from threading import Event
from typing import Any, TypeVar

from pydantic import BaseModel

from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMResponseError, LLMTransportError
from adaptive_document_agent.services.llm.gateway import LLMGateway
from .prompting import untrusted_document_message

Draft = TypeVar('Draft', bound=BaseModel)


class SummaryDraftProtocolError(ValueError):
    """No schema-valid draft was obtained within the format budget."""


def author_draft(
    gateway: LLMGateway, messages: list[dict[str, str]], schema: type[Draft],
    audit: dict[str, Any], *, cancelled: Event | None = None,
) -> Draft:
    """Two draft attempts, or one draft plus a patch with one gateway repair."""
    from .summary_writer_copy import writer_schema, bind_writer_copy
    canonical_schema = schema
    schema = writer_schema(schema)
    def canonical(draft):
        bound, count = bind_writer_copy(draft, canonical_schema)
        if count:
            audit['writer_copy_binding'] = dict(reference_count=count,
                quote_source='exact_full_current_paragraph', model_owns='part_id_and_meaning_index',
                semantic_approval=False)
        return bound
    original = list(messages)
    attempts = audit.setdefault('draft_format_attempts', [])
    for attempt in range(2):
        if cancelled is not None and cancelled.is_set():
            raise CancelledError('Summary draft cancelled')
        record = {'attempt': attempt+1}
        attempts.append(record)
        try:
            draft = gateway.generate_structured(messages, schema, stage='presentation',
                allow_repair=False, cancelled=cancelled)
            record['status'] = 'success'
            return canonical(draft)
        except LLMStructuredOutputError as exc:
            record.update(status='invalid_format', raw_response=exc.response.text,
                          validation_detail=str(exc.__cause__ or exc))
            if attempt:
                raise SummaryDraftProtocolError('Summary draft format repair exhausted: '+
                                                record['validation_detail']) from exc
            from .summary_format_fields import (string_failure_context, field_repair_messages,
                                                string_repair_schema, apply_string_repairs)
            context = string_failure_context(exc.response.text, schema)
            if context is not None:
                if cancelled is not None and cancelled.is_set():
                    raise CancelledError('Summary draft cancelled')
                data, paths, fields = context
                patch_record = {'attempt': 2, 'repair_kind': 'targeted_strings', 'fields': fields}
                attempts.append(patch_record)
                try:
                    replacements = gateway.generate_structured(field_repair_messages(fields), string_repair_schema(fields),
                        stage='presentation', cancelled=cancelled)
                    patch_record['replacements'] = replacements.model_dump(mode='json')
                    draft = apply_string_repairs(data, paths, replacements, schema)
                except LLMTransportError:
                    raise
                except (ValueError, LLMResponseError) as repair_error:
                    patch_record.update(status='invalid_format', validation_detail=str(repair_error))
                    raise SummaryDraftProtocolError('Summary draft format repair exhausted: '+str(repair_error)) from repair_error
                patch_record['status'] = 'success'
                return canonical(draft)
            messages = original + [untrusted_document_message(json.dumps(record,ensure_ascii=False)),
                {'role':'user','content':'Repair the response format against the schema. Preserve the '
                 'semantic audience/content scope of the original instructions, every required claim '
                 'and qualification, identity and exact fact IDs. Evidence context does not expand that '
                 'scope during format recovery. Pages are logical groups; Python '
                 'paginates complete items. Do not drop required content to fit a group. Split overlong prose into '
                 'complete items with its original evidence. If the schema and user permit a supporting '
                 'appendix, move detailed supporting items there instead of bloating the body. '
                 'Do not invent or truncate claims.'}]
