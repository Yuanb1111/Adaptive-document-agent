"""Restore a displayed table cell unit only from its literal source phrase."""
import re
from .source_quotes import continuous_quote_passages, normalize_quote

_HEADER_UNIT = re.compile(r"\((seconds?|minutes?|hours?|days?|weeks?|months?|years?)\)\s*$", re.I)
_BARE = re.compile(r"(?:approximately\s+|about\s+)?[+−-]?\d+(?:\.\d+)?", re.I)


def literal_table_units(item, pages):
    """Preserve raw cells; display the complete quote when its header names a unit.

    No conversion or missing unit is inferred. The whole extended phrase must
    be present in this item's continuous literal evidence on the cited page.
    """
    if not item.comparison_table:
        return None
    table = item.comparison_table.model_copy(deep=True)
    passages = [normalize_quote(q.text) for q in continuous_quote_passages(item.evidence, pages)]
    for column, header in enumerate(table.headers):
        match = _HEADER_UNIT.search(header)
        if not match:
            continue
        unit = match[1].casefold()
        for row in table.rows:
            cell = row[column]
            if _BARE.fullmatch(cell):
                phrase = cell + ' ' + unit
                if any(normalize_quote(phrase) in passage for passage in passages):
                    row[column] = phrase
    return table
