"""Read uniform explicit unit rows when a quoted grid has no parsed table."""
import re

from adaptive_document_agent.extraction.normalizer import infer_unit_defaults
from adaptive_document_agent.extraction.numeric_parser import parse_number
from .source_quotes import normalize_quote

_UNIT = re.compile(r"(?:[A-Z]{3}|US\$|HK\$)['’]000s?", re.I)
_CELL = r'(?:[+−-]?\d[\d,]*(?:\.\d+)?|\(\d[\d,]*(?:\.\d+)?\)|[—–-])'
_PERIOD_ROW = re.compile(r'(?:(?:FY|\d{1,2}M)?(?:19|20)\d{2}\s*)+', re.I)


def uniform_quoted_rows(source, quote):
    """Require a complete quoted repeated-unit header and matching-width rows.

    Mixed unit headers, partial rows and units elsewhere on the page confer no
    support. Accounting signs stay literal. This does not assign metric meaning.
    """
    from .brief_table_evidence import canonical_quantity, _number, _SCALES
    quoted = normalize_quote(quote)
    header = None
    supported = set()
    for line in source.splitlines():
        text = line.strip()
        tokens = text.split()
        if tokens and all(_UNIT.fullmatch(token) for token in tokens):
            defaults = [infer_unit_defaults(token) for token in tokens]
            units = {(d.currency, d.scale) for d in defaults}
            header = None
            if (len(tokens) >= 2 and len(units) == 1 and normalize_quote(text) in quoted
                    and defaults[0].currency and defaults[0].scale in _SCALES):
                header = (len(tokens), defaults[0].currency, defaults[0].scale)
            continue
        if (_UNIT.search(text) or _PERIOD_ROW.fullmatch(text)
                or re.fullmatch(r'(?:(?:%|percent|times|units|days)\s*)+', text, re.I)
                or re.search(r'[.!?]$|^Note\b', text, re.I)):
            header = None
        if header is None or not text or normalize_quote(text) not in quoted:
            continue
        count, currency, scale = header
        row = re.fullmatch(r'(.+?)\s+(' + _CELL + r'(?:\s+' + _CELL + r'){' + str(count-1) + r'})', text)
        if (not row or re.search(r'%|\b(?:times|units|days)\b', row[1], re.I)
                or not re.search(r'[A-Za-z\u4e00-\u9fff]', row[1])
                or re.search(r'\s' + _CELL + r'$', row[1])):
            continue
        for cell in row[2].split():
            number = parse_number(cell.replace('−', '-'))
            if number is not None:
                supported.add(canonical_quantity(currency, _number(number.value), _SCALES[scale]))
    return supported
