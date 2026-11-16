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


def supplied_passage_hints(quote,pages,*,limit=3):
    """Find bounded original reading aids only within the caller's supplied pages.

    These are diagnostics, not a page relocation or an accepted citation. The
    caller still rejects the draft and requires a new literal quote and review.
    """
    target=normalize_quote(quote).split()
    if not target:return []
    candidates=[]
    for page,source in pages.items():
        passage=source_passage_hint(quote,source)
        if passage is not None:
            score=SequenceMatcher(None,target,normalize_quote(passage).split(),autojunk=False).ratio()
            candidates.append((score,page,passage))
    candidates.sort(key=lambda item:(-item[0],item[1]))
    return [dict(page=page,text=passage) for _,page,passage in candidates[:limit]]
