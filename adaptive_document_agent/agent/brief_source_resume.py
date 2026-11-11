"""Retain retrieval choices for an identical reporting environment, never verdicts."""
import json

from .brief_review_checkpoint import context_key


def retained_source_pages(result, available):
    environment = context_key(None, None, result)
    for warning in reversed(result.validation_warnings):
        if warning.code != 'executive_brief_review_checkpoint':
            continue
        try:
            record = json.loads(warning.message)
            if record.get('environment_key') != environment:
                continue
            context = record['source_context']
            # Companions are appended after the primary retrieval, before
            # identity/definition additions. Their first occurrence supplies
            # an exact boundary even for older checkpoints without seed pages.
            companions = set(context.get('companion_context_pages', []))
            selected = []
            for entry in context['source_excerpt_scope']:
                if entry['page'] in companions:
                    break
                selected.append(entry['page'])
            else:
                continue  # No proven boundary; request a fresh selection.
            if (1 <= len(selected) <= 10 and len(set(selected)) == len(selected)
                    and set(selected) <= set(available)):
                return selected
        except (ValueError, KeyError, TypeError):
            continue
    return None
