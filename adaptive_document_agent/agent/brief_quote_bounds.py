"""Split complete literal model quotations without dropping source words."""
from copy import deepcopy
from adaptive_document_agent.services.source_quotes import normalize_quote


def bounded_quote_item(value, excerpts):
    """Reformat only overlong quotes; unknown fields and factual errors survive.

    The original model envelope is retained by the caller's audit. A quote is
    eligible only when the complete passage is on the exact supplied page.
    Splitting cannot add evidence, trim a qualification or exceed four quotes.
    """
    if not isinstance(value, dict) or not isinstance(value.get('evidence'), list):
        return value
    result = deepcopy(value)
    quotes = []
    for quote in value['evidence']:
        if not isinstance(quote, dict) or set(quote) != {'page', 'text'}:
            return value
        text, page = quote['text'], quote['page']
        if not isinstance(text, str) or type(page) is not int:
            return value
        if len(text) <= 1800:
            quotes.append(quote)
            continue
        if not normalize_quote(text) or normalize_quote(text) not in normalize_quote(excerpts.get(page, '')):
            return value
        remaining = text
        parts = []
        while len(remaining) > 1800:
            cut = remaining.rfind(' ', 8, 1801)
            if cut < 8:
                return value
            parts.append(remaining[:cut])
            remaining = remaining[cut:].lstrip()
        parts.append(remaining)
        if any(len(part) < 8 for part in parts) or normalize_quote(' '.join(parts)) != normalize_quote(text):
            return value
        quotes.extend({'page': page, 'text': part} for part in parts)
    if len(quotes) > 4:
        return value
    result['evidence'] = quotes
    return result
