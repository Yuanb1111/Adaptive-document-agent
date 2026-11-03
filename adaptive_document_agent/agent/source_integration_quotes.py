"""Resolve model-selected line ranges to continuous text on their physical PDF page."""
import re
from adaptive_document_agent.services.source_quotes import normalize_quote


def numbered_source_pages(pages):
    output = []
    for page in pages:
        lines = page['text'].splitlines(keepends=True)
        options = []
        start = 0
        while start < len(lines):
            end = start + 1
            while end < len(lines) and len(''.join(lines[start:end + 1]).strip()) <= 1800:
                end += 1
            length = len(''.join(lines[start:end]).strip())
            if 8 <= length <= 1800:
                options.append(dict(ref=f'@lines[{start + 1}-{end}]', characters=length))
            # An individually overlong source line remains in full below;
            # only a literal substring, not an invalid whole-line option, fits.
            start = end
        output.append(dict(page=page['page'], lines=[
            f'{n} | {line}' for n, line in enumerate(page['text'].splitlines(), 1)],
            evidence_reference_options=options))
    return output


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
                quote_limit = type(item).model_json_schema()['properties']['evidence']['maxItems']
                raise ValueError(f'Evidence range {locator} on PDF page {quote.page} '
                                 f'has {len(literal)} characters; it must resolve to 8–1800 literal characters. '
                                 'Choose a shorter evidence_reference_options span or a smaller exact range; '
                                 f'at most {quote_limit} representative quotations fit this object.')
            quote.text = literal
    return bound
