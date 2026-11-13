"""Offer an original passage for a rejected quote; similarity never grants evidence."""
from difflib import SequenceMatcher
import re

from .source_quotes import normalize_quote


def source_passage_hint(quote,source):
    """Return a complete bounded paragraph solely as untrusted correction feedback."""
    target=normalize_quote(quote).split()
    if not target:return None
    candidates=[part.strip() for part in re.split(r'\n[ \t]*\n',source)
                if 8<=len(part.strip())<=1800]
    if not candidates:return None
    scored=[(SequenceMatcher(None,target,normalize_quote(part).split(),autojunk=False).ratio(),part)
            for part in candidates]
    score,passage=max(scored,key=lambda pair:pair[0])
    return passage if score>=.6 else None
