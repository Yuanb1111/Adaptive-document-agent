"""Literal day-count parameters in quoted calculation definitions."""
import re

_COUNT = re.compile(r'\b\d+(?:\.\d+)?\s+days?\s+for\s+(?:a|an|the)\s+'
    r'(?:(?:given|calendar|financial)\s+)?(?:year|(?:[\w]+[- ]months?\s+)?period)\b', re.I)
_DEFINITION = re.compile(r'\b(?:calculat\w*|multiply\w*|multipli\w*|convention|defined|definition|uses?)\b', re.I)
_SOURCE_CONTEXT = re.compile(r'\b(?:multiply\w*|multipli\w*|convention|formula|definition|day[- ]count)\b'
                             r'|\bnumber of days\b', re.I)


def literal_day_count_conventions(text):
    """Read explicit parameters, never derive a duration or a measurement."""
    text = ' '.join(text.split())
    return {match[0] for match in _COUNT.finditer(text)
            if _SOURCE_CONTEXT.search(text[max(0, match.start() - 180):match.start()])}


def mask_day_count_conventions(text, phrases):
    """Mask only the same literal parameter in a calculation-definition clause."""
    for phrase in sorted(set(phrases), key=len, reverse=True):
        pattern = re.compile(r'(?<!\w)' + r'\s+'.join(re.escape(part) for part in phrase.split()) + r'(?!\w)', re.I)
        spans = [m.span() for m in pattern.finditer(text)
                 if _DEFINITION.search(text[max(0, m.start() - 180):m.start()])]
        for start, end in reversed(spans):
            text = text[:start] + ' ' * (end - start) + text[end:]
    return text
