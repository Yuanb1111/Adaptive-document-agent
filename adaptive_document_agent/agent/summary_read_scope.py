"""Supply only editable source ranges while preserving original line addresses."""
import json

from .prompting import untrusted_document_message


class TargetedReadScopeError(ValueError):
    """A proposal crossed a protected boundary inside a known source block."""


def targeted_source_messages(source_messages, blocks, ranges):
    """Keep source text out of the request unless its ownership may be changed.

    Binding still uses the complete original blocks. Sparse numbered excerpts
    therefore cannot change source coordinates, widen quotes, or replace a
    previously accepted fact from context.
    """
    excerpts = []
    for block in blocks:
        selected = [span for span in ranges if span['block_id'] == block.id]
        if not selected:
            continue
        excerpts.append(dict(block_id=block.id, page=block.page,
            allowed_ranges=[dict(start_line=s['start_line'], end_line=s['end_line']) for s in selected],
            lines=[[n, line] for n, line in enumerate(block.text.splitlines(keepends=True), 1)
                   if any(s['start_line'] <= n <= s['end_line'] for s in selected)]))
    return [message for message in source_messages if message['role'] == 'system'] + [
        untrusted_document_message(json.dumps(excerpts, ensure_ascii=False))]
