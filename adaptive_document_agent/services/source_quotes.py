"""Normalize PDF typography without removing words, values or qualifications."""

import re
import unicodedata


def normalize_quote(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    # Table leaders are layout, not omitted prose. Leave individual decimal
    # points and punctuation intact, and never bridge omitted source words.
    text = re.sub(r"(?<!\w)(?:\.\s*){2,}", " ", text)
    return " ".join(text.casefold().split())
