"""Apply the existing copy allowance after exact quantity IDs become text."""
import json

from pydantic import ValidationError

from adaptive_document_agent.services.llm.base import LLMResponse
from adaptive_document_agent.services.llm.exceptions import LLMStructuredOutputError
from .brief_patch_capacity import compact_overlong_patch


def validate_expanded_patch(gateway, messages, schema, wire, expanded, audit, *, cancelled=None):
    """Correct only overflow caused by a completed reference-array expansion.

    This is the same one-copy correction used for an overlong literal reply,
    reached after transport resolution. Other fields, sibling patches and source
    bindings remain unchanged; every merged claim still needs independent review.
    """
    try:
        return schema.model_validate(expanded)
    except ValidationError as invalid:
        failures = invalid.errors(include_input=False, include_url=False)
        if not failures or any(f['type'] != 'string_too_long' or len(f['loc']) != 2
                or f['loc'][1] != 'text' or not isinstance(wire.get(f['loc'][0], {}).get('text'), list)
                for f in failures):
            raise
        error = LLMStructuredOutputError('Restored native-quantity text exceeds the copy limit',
            response=LLMResponse(text=json.dumps(expanded, ensure_ascii=False)))
        record = audit.setdefault('expanded_quantity_copy_capacity', {})
        if record:
            raise error from invalid
        return compact_overlong_patch(gateway, [*messages, dict(role='system',content=
            'All quantity reference IDs in this completed patch have already been restored to exact '
            'source-native strings. Correct only the requested overflowing text as a literal STRING, '
            'not a reference array. Keep exact retained amounts, signs and units; do not round or '
            'rescale. Use shared explicit period/unit scope and concise material qualifications. '
            'The other successful sibling patches and every evidence/reference field are frozen. '
            'This copy correction grants no source or semantic approval.')], schema, error, record,
            cancelled=cancelled)
