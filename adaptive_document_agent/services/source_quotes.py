"""Normalize PDF typography without removing words, values or qualifications."""

import re
import unicodedata
from dataclasses import dataclass


def normalize_quote(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    # Table leaders are layout, not omitted prose. Leave individual decimal
    # points and punctuation intact, and never bridge omitted source words.
    text = re.sub(r"(?<![\d.])(?:\.\s*){2,}", " ", text)
    return " ".join(text.casefold().split())


def split_literal_quote(text: str, limit: int = 1800) -> list[str]:
    """Bound citations without dropping words, signs, units or qualifications."""
    parts, remaining = [], text
    while len(remaining) > limit:
        cuts = list(re.finditer(r'\s+', remaining[8:limit + 1]))
        if not cuts:
            raise ValueError('A literal citation cannot be split at a safe word boundary')
        cut = 8 + cuts[-1].start()
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if len(remaining) < 8 and parts:
        # Keep a short final word with its preceding chunk.
        previous = parts.pop()
        cut = max(previous.rfind(' '), previous.rfind('\n'))
        if cut < 8:
            raise ValueError('A literal citation has an unbounded final fragment')
        parts.append(previous[:cut])
        remaining = previous[cut:].lstrip() + ' ' + remaining
    parts.append(remaining)
    if len(parts) > 4 or any(len(p) < 8 or len(p) > limit for p in parts):
        raise ValueError('A literal citation exceeds the bounded evidence capacity')
    if normalize_quote(' '.join(parts)) != normalize_quote(text):
        raise ValueError('Splitting altered literal evidence')
    return parts


@dataclass(frozen=True)
class QuotePassage:
    page: int
    text: str


def continuous_quote_passages(quotes, pages):
    """Rejoin adjacent literal chunks only when their entire union is on a page.

    Formatting a long citation into short chunks must not weaken conditional
    completeness checks. Discontinuous passages never become one quotation.
    """
    passages = []
    for quote in quotes:
        if (passages and passages[-1].page == quote.page
                and normalize_quote(passages[-1].text + ' ' + quote.text)
                in normalize_quote(pages.get(quote.page, ''))):
            passages[-1] = QuotePassage(quote.page, passages[-1].text + ' ' + quote.text)
        else:
            passages.append(QuotePassage(quote.page, quote.text))
    return passages


def continuous_quote_texts(quotes, pages):
    return [q.text for q in continuous_quote_passages(quotes, pages)]
