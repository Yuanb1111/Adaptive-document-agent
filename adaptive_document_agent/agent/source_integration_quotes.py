"""Resolve model-selected line ranges to continuous text on their physical PDF page."""
import re
from bisect import bisect_left, bisect_right
from functools import lru_cache
from itertools import accumulate
from adaptive_document_agent.services.source_quotes import normalize_quote


class SourceQuoteCapacityError(ValueError):
    """A selected literal range cannot fit the object's remaining quote slots."""


def numbered_source_pages(pages):
    from .source_table_cells import phrase_cell_options
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
        output.append(dict(**{k: v for k, v in page.items() if k != 'text'}, lines=[
            f'{n} | {line}' for n, line in enumerate(page['text'].splitlines(), 1)],
            evidence_reference_options=options,
            table_cell_reference_options=[dict(ref=o['ref'], chars=o['characters'], preview=o['text'][:48])
                for o in phrase_cell_options(page['page'], page['text'])]))
    return output


def _literal_parts(literal, slots):
    """Use the fewest slots; prefer physical lines, then whole-word boundaries.

    All parts are slices of the same selected range. Even its interior
    whitespace is retained. Never cut a source token or discard a short tail.
    """
    size = len(literal)
    if size < 8 or size > 1800 * slots:
        return None
    if size <= 1800:
        return [literal]
    if any(len(word) > 1800 for word in literal.split()):
        return None
    line_ends = list(accumulate(len(line) for line in literal.splitlines(keepends=True)))[:-1]
    word_boundaries = sorted({offset for match in re.finditer(r'\s+', literal) for offset in match.span()})

    @lru_cache(None)
    def split(start, available):
        if size - start <= 1800:
            return (size,) if len(literal[start:].strip()) >= 8 else None
        if available < 2:
            return None
        low = max(start + 8, size - (available - 1) * 1800)
        high = min(start + 1800, size - 8)
        for boundaries in (line_ends, word_boundaries):
            candidates = boundaries[bisect_left(boundaries, low):bisect_right(boundaries, high)]
            for cut in reversed(candidates):
                if len(literal[start:cut].strip()) < 8:
                    continue
                tail = split(cut, available - 1)
                if tail is not None:
                    return (cut, *tail)
        return None

    for capacity in range((size + 1799) // 1800, slots + 1):
        cuts = split(0, capacity)
        if cuts is not None:
            return [literal[start:end] for start, end in zip((0, *cuts[:-1]), cuts)]
    return None


def bind_source_quotes(draft, pages, *, selected_phrase_evidence=False):
    bound = draft.model_copy(deep=True)
    for item in [*bound.decisions, *bound.additions]:
        evidence = []
        quote_limit = type(item).model_json_schema()['properties']['evidence']['maxItems']
        for position, quote in enumerate(item.evidence):
            reference = re.fullmatch(r'(@lines\[(\d{1,6})(?:-(\d{1,6}))?\])(?:\s+(.+))?', quote.text, re.S)
            if not reference:
                evidence.append(quote)
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
            # Reserve at least one quotation for every later submitted source.
            remaining = len(item.evidence) - position - 1
            parts = _literal_parts(literal, quote_limit - len(evidence) - remaining)
            if parts is None:
                raise SourceQuoteCapacityError(f'Evidence range {locator} on PDF page {quote.page} '
                                 f'has {len(literal)} characters; it must resolve to 8–1800 literal characters. '
                                 'Choose a shorter evidence_reference_options span or a smaller exact range; '
                                 f'at most {quote_limit} representative quotations fit this object.')
            evidence.extend(type(quote)(page=quote.page, text=part) for part in parts)
        item.evidence = evidence
        from .source_table_cells import bind_table_cells
        bind_table_cells(item, pages, selected_phrase_evidence=selected_phrase_evidence)
    return bound
