"""Bound selection output capacity and preserve content during format repair."""
import json

from adaptive_document_agent.models import ValidationIssue
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .presentation_budget_output import complete_budget_output, SELECTION_TOKEN_LIMITS


def selection_request(gateway, messages, schema, result, attempt, *, max_tokens=8000,
                      capacity_tokens=None):
    output = {}
    try:
        return complete_budget_output(gateway, messages, schema, output,
            audit_key='attempts', token_limits=(max_tokens, capacity_tokens or max_tokens * 2))
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
    finally:
        if any(entry['status'] == 'truncated' for entry in output.get('attempts', [])):
            result.validation_warnings.append(ValidationIssue(
                code='retained_selection_output_capacity', stage='presentation', severity='info',
                message=json.dumps(output, ensure_ascii=False)))
