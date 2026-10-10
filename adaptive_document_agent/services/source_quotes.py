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
