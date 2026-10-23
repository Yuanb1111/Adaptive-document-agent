"""Exact overview feedback and session-owned diagnostics, without source logging."""
import json

from pydantic import ValidationError

from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from adaptive_document_agent.services.llm.structured import validate_structured_text
from adaptive_document_agent.utils.pipeline_version import PIPELINE_VERSION


def overview_failure(error, schema, attempt):
    record = dict(attempt=attempt, operation=schema.__name__, status='invalid_format')
    if isinstance(error, LLMStructuredOutputError):
        output = error.response
        record['raw_response'] = output.text
        if output.usage is not None:
            record['usage'] = output.usage.model_dump(include={
                'provider', 'model', 'resolved_model', 'finish_reason', 'output_tokens',
                'input_tokens', 'latency_ms'}, mode='json')
        if output.usage is not None and output.usage.finish_reason == 'length':
            record.update(status='truncated', schema_errors=[dict(type='output_truncated', loc=[],
                msg='Regenerate a complete compact overview from the original summaries.')])
            return record
        try:
            validate_structured_text(output.text, schema)
        except (ValueError, TypeError) as invalid:
            error = invalid
    if isinstance(error, ValidationError):
        record['schema_errors'] = json.loads(error.json(include_input=False, include_url=False))
    else:
        record['schema_errors'] = [dict(type='invalid_json', loc=[], msg='Return one complete JSON object matching the schema.')]
    return record


def overview_exception(error, attempts):
    """Public message names failing fields; raw replies remain in opt-in download."""
    last = attempts[-1]
    details = '; '.join('.'.join(map(str, issue['loc'])) + ' (' + issue['type'] + ')'
                        for issue in last['schema_errors'][:8])
    response = error.response if isinstance(error, LLMStructuredOutputError) else LLMResponse(text='')
    failure = LLMStructuredOutputError(
        f'Document overview (DiscoveryOverview) failed after {len(attempts)} attempts: {details}. '
        'Successful section results remain cached. Download failure diagnostics for the exact field errors.',
        response=response)
    failure.diagnostics = dict(pipeline_version=PIPELINE_VERSION, stage='discovery',
        operation='DiscoveryOverview', attempts=attempts,
        contains_model_output=True)
    return failure
