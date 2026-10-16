"""Bind a quoted currency/type row to its separate quoted scale declaration."""
import re

from adaptive_document_agent.extraction.normalizer import infer_unit_defaults
from .source_quotes import normalize_quote

_TOKEN = re.compile(r'(?:[A-Z]{3}|US\$|HK\$|S\$|[$€£¥￥]|%)', re.I)
_SCALE = re.compile(r'\(?\s*in\s+(thousands?|millions?|billions?|trillions?)'
                    r'(?:\s*,?\s*except\s+(?:for\s+)?percentages?)?\s*\)?', re.I)
_FACTORS = {'thousand': 1000, 'million': 1000000, 'billion': 1000000000,
            'trillion': 1000000000000}


def paired_column_unit_supported(table, column, currency, scale, source, quoted, locate):
    """Require literal complete header rows and one exact aligned column unit.

    Metadata alone, a unit elsewhere on the page, partial column rows and
    conflicting declarations cannot authorize a quantity. No values are changed.
    """
    from .brief_table_evidence import canonical_quantity
    width = len(table.headers) - 1
    if not 1 <= column <= width:
        return False
    candidates, scales = set(), set()
    for raw in table.raw_header_lines:
        located = locate(raw, source)
        if not located or normalize_quote(located) not in quoted:
            continue
        text = located.strip()
        declaration = _SCALE.fullmatch(text)
        if declaration:
            scales.add(_FACTORS[declaration[1].casefold().rstrip('s')])
            continue
        tokens = text.split()
        if len(tokens) != width or not all(_TOKEN.fullmatch(token) for token in tokens):
            continue
        # Every percentage marker must agree with the actual column type.
        # This prevents a short/misaligned currency row from lending units.
        if any((token == '%') != (index < len(table.column_types)
                                 and table.column_types[index] == 'percentage')
               for index, token in enumerate(tokens, 1)):
            continue
        unit = infer_unit_defaults(tokens[column-1])
        if unit.currency:
            candidates.add(canonical_quantity(unit.currency, '', '')[0])
    return scales == {scale} and candidates == {currency}
