"""Bounded output-capacity recovery without changing budget semantics or source context."""
from concurrent.futures import CancelledError

from adaptive_document_agent.services.llm.exceptions import (
    LLMStructuredOutputError, LLMTransportError, PrivacyViolationError,
)

SELECTION_TOKEN_LIMITS = (24000, 40000)
REVIEW_TOKEN_LIMITS = (16000, 24000)


def complete_budget_output(gateway, messages, schema, record, *, audit_key, token_limits,
                           stage='presentation'):
    """Retry one proven length truncation from the identical complete messages.

    A partial JSON response is retained for diagnosis only. It is never parsed,
    continued, merged, accepted, or passed to an independent semantic reviewer.
    """
    attempts = record.setdefault(audit_key, [])
    for attempt, limit in enumerate(token_limits, 1):
        physical = dict(attempt=attempt, requested_max_tokens=limit, status='pending',
                        capacity_retry=False)
        attempts.append(physical)
        try:
            response = gateway.generate_structured(messages, schema, stage=stage,
                allow_repair=False, max_tokens=limit)
        except Exception as exc:
            truncated = False
            if isinstance(exc, LLMStructuredOutputError):
                output = exc.response
                physical.update(raw_response=output.text, response_chars=len(output.text),
                                transport_attempt_count=len(output.attempts))
                if output.usage is not None:
                    physical['usage'] = output.usage.model_dump(include={
                        'provider', 'model', 'resolved_model', 'input_tokens', 'output_tokens',
                        'reasoning_tokens', 'finish_reason', 'latency_ms', 'status'}, mode='json')
                    truncated = output.usage.finish_reason == 'length'
            elif isinstance(exc, LLMTransportError):
                physical['transport_attempt_count'] = len(exc.attempts)
            status = ('truncated' if truncated else
                      'cancelled' if isinstance(exc, CancelledError) else
                      'privacy_blocked' if isinstance(exc, PrivacyViolationError) else
                      'transport_error' if isinstance(exc, LLMTransportError) else
                      'invalid_format' if isinstance(exc, LLMStructuredOutputError) else 'failed')
            physical.update(status=status, error_type=type(exc).__name__, error=str(exc),
                            capacity_retry=truncated and attempt < len(token_limits))
            if physical['capacity_retry']:
                continue
            raise
        physical['status'] = 'response_received'
        return response
