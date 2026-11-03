"""Resolve model-selected line ranges to continuous text on their physical PDF page."""
import re
from adaptive_document_agent.services.source_quotes import normalize_quote


def numbered_source_pages(pages):
    return [{'page': p['page'], 'lines': [
        f'{n} | {line}' for n, line in enumerate(p['text'].splitlines(), 1)]} for p in pages]


def bind_source_quotes(draft, pages):
    bound = draft.model_copy(deep=True)
    for item in [*bound.decisions, *bound.additions]:
        for quote in item.evidence:
            reference = re.fullmatch(r'(@lines\[(\d{1,6})(?:-(\d{1,6}))?\])(?:\s+(.+))?', quote.text, re.S)
            if not reference:
                continue
            locator, first, last, transcription = reference.groups()
            start, end = int(first), int(last or first)
            lines = pages.get(quote.page, '').splitlines(keepends=True)
            if not 1 <= start <= end <= len(lines):
                raise ValueError(f'Invalid evidence range {locator} on PDF page {quote.page}.')
            literal = ''.join(lines[start - 1:end]).strip()
            if transcription and normalize_quote(transcription) != normalize_quote(literal):
                raise ValueError(f'Transcription differs from {locator} on PDF page {quote.page}. '
                                 'Choose the correct range and return the line reference alone.')
            if not 8 <= len(literal) <= 1800:
                raise ValueError(f'Evidence range {locator} on PDF page {quote.page} '
                                 'must resolve to 8–1800 literal characters.')
            quote.text = literal
    return bound
