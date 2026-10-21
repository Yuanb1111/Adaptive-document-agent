"""Bounded format recovery and page locators for introductory reading calls."""
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError, LLMTransportError


def reading_failure_kind(error, audit):
    if isinstance(error, LLMTransportError):
        return 'provider'
    if isinstance(error, LLMStructuredOutputError) and error.response.usage and error.response.usage.finish_reason == 'length':
        return 'truncated'
    def repairs(value):
        if isinstance(value, dict):
            if 'format_repair' in value:
                yield value['format_repair']
            for child in value.values():
                yield from repairs(child)
        elif isinstance(value, list):
            for child in value:
                yield from repairs(child)
    return 'format' if any(r.get('status') == 'failed' for r in repairs(audit)) else 'evidence'


def reading_request(gateway, messages, schema, blocks, cancelled, record):
    metadata = {'source_page_start': min(b.page for b in blocks),
                'source_page_end': max(b.page for b in blocks)}
    try:
        return gateway.generate_structured(messages, schema, stage='presentation',
            allow_repair=False, cancelled=cancelled, request_metadata=metadata)
    except LLMStructuredOutputError as exc:
        diagnostic = record.setdefault('format_repair', {})
        diagnostic.update(error=str(exc), validation_detail=str(exc.__cause__ or exc),
                          raw_response=exc.response.text)
        if exc.response.usage and exc.response.usage.finish_reason == 'length':
            diagnostic['status'] = 'truncated'
            raise
        try:
            response = gateway.repair_structured_output(exc, schema, stage='presentation',
                cancelled=cancelled, request_metadata=metadata, diagnostics=diagnostic)
        except Exception as failure:
            diagnostic.update(status='failed', repair_error=str(failure),
                              repair_validation_detail=str(failure.__cause__ or failure))
            raise
        diagnostic['status'] = 'repaired'
        return response
