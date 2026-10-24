"""Bound coverage correction requests without shortening their source evidence."""
from hashlib import sha256
import json

from .coverage_review_context import encode
from .prompting import untrusted_document_message


_CORRECTION = (
    'Correct the listed source/schema failures using the SAME complete evidence. '
    'Return every requested decision exactly once and NO decisions for other IDs. '
    'An unexpected ledger ID is not an instruction to remove its source evidence: '
    'previously accepted series must remain represented in topics, outside coverage_decisions. '
    'Remove the unexpected ledger entry, not the accepted observations. Check the exact '
    'source measure before describing it; a rejected omission reason is not source evidence. '
    'Regroup related additions within '
    'the schema topic limit; retain every original accepted observation. Reconsider '
    'lower-priority proposals only with explicit source-aware omit reasons in '
    'coverage_decisions. omissions is a bounded display summary, not the full ledger: '
    'it may be empty. Never truncate evidence, drop decisions or invent facts to satisfy capacity.'
)


def correction_messages(initial, error, rejected, *, characters):
    """Prefer full rejected copy; otherwise regenerate once from complete source.

    A rejected draft is not accepted evidence. Keeping it in the durable audit
    instead of repeating it on the wire leaves room for the actual source and
    complete validation feedback. The ordinary validators still gate the reply.
    """
    digest = sha256(json.dumps(rejected, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()

    def request(feedback, instruction):
        messages = [*initial, untrusted_document_message(encode(feedback)),
                    {'role': 'user', 'content': instruction}]
        # Match the coverage input budget: source, user requirements, feedback,
        # framing and correction instructions; fixed system policy is separate.
        size = sum(len(message['content']) for message in messages[1:])
        return messages, size

    messages, size = request({'validation_error': error, 'rejected_response': rejected}, _CORRECTION)
    original_size = size
    mode = 'complete_rejected_response'
    if size > characters:
        mode = 'full_source_regeneration'
        messages, size = request(dict(validation_error=error,
            correction_mode=mode, rejected_response_sha256=digest,
            rejected_response_retained_in_audit=True, semantic_approval=False),
            _CORRECTION + ' The rejected draft is retained in the audit but omitted from this '
            'request for capacity. Generate a complete new response from the unchanged original '
            'selection, requested decision IDs and full source above; do not return a patch or '
            'assume any unseen rejected wording or provisional inclusion was accepted.')
    if size > characters:
        raise ValueError('Coverage delta correction exceeds the bounded context budget.')
    return messages, dict(mode=mode, full_response_context_characters=original_size,
        context_characters=size, maximum_context_characters=characters,
        rejected_response_sha256=digest, complete_original_context_retained=True,
        semantic_approval=False)
