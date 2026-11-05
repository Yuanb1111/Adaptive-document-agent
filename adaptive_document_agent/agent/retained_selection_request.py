"""Retain rejected selection output and allow one content-preserving format repair."""
import json

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError


def selection_request(gateway, messages, schema, result, attempt, *, max_tokens=8000):
    try:
        return gateway.generate_structured(messages, schema, stage='presentation',
                                           allow_repair=False, max_tokens=max_tokens)
    except LLMStructuredOutputError as exc:
        diagnostic = dict(attempt=attempt + 1, error=str(exc),
                          validation_detail=str(exc.__cause__ or exc),
                          raw_response=exc.response.text)
        try:
            if exc.response.usage and exc.response.usage.finish_reason == 'length':
                diagnostic['status'] = 'truncated'
                raise
            value = gateway.repair_structured_output(exc, schema, stage='presentation',
                                                      diagnostics=diagnostic, max_tokens=max_tokens)
            diagnostic['status'] = 'repaired'
            return value
        except Exception as failure:
            diagnostic.setdefault('status', 'failed')
            diagnostic['repair_error'] = str(failure)
            raise
        finally:
            result.validation_warnings.append(ValidationIssue(
                code='retained_selection_format_repair', stage='presentation', severity='info',
                message=json.dumps(diagnostic, ensure_ascii=False)))
