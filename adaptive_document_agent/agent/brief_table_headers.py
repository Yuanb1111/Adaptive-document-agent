"""Retain literal table headers with an unambiguously cited complete row."""
from copy import deepcopy
import re

from adaptive_document_agent.extraction.numeric_parser import parse_number
from adaptive_document_agent.services.source_quotes import normalize_quote
from adaptive_document_agent.services.brief_table_evidence import _quoted_complete_row


def _literal_header(table, page, excerpt):
    spans = []
    for header in table.raw_header_lines:
        compact = ''.join(header.split())
        if not compact:
            continue
        # Recover source spacing without joining separate source passages or
        # accepting invented header text from extraction metadata.
        match = re.search(r'\s*'.join(re.escape(c) for c in compact), page.text, re.I)
        if match is None:
            return None
        spans.append(match.span())
    if not spans:
        return None
    literal = page.text[min(s[0] for s in spans):max(s[1] for s in spans)]
    if not 8 <= len(literal) <= 1800:
        return None
    if not any(normalize_quote(literal) in normalize_quote(passage)
               for passage in excerpt.split('[SEPARATE SOURCE PASSAGE]')):
        return None
    return literal


def bind_table_headers(value, result, excerpts):
    """Add source context, never values, author copy or a validation verdict.

    Partial rows and competing grids cannot acquire a table's dates or units.
    Existing quotations are immutable; the normal four-quote limit and every
    source/meaning gate still apply. Return bindings for the transport audit.
    """
    if not isinstance(value, dict) or not isinstance(value.get('evidence'), list):
        return value, []
    pages = {page.page_number: page for page in result.document.pages}
    evidence = value['evidence']
    if not 1 <= len(evidence) < 4:
        return value, []
    additions, bindings = [], []
    for quote in evidence:
        if (not isinstance(quote, dict) or set(quote) != {'page', 'text'}
                or type(quote['page']) is not int or quote['page'] <= 0):
            return value, []
        page = pages.get(quote['page'])
        if not page or not isinstance(quote['text'], str):
            return value, []
        quoted = normalize_quote(quote['text'])
        excerpt = excerpts.get(page.page_number, '')
        if not quoted or quoted not in normalize_quote(page.text) or quoted not in normalize_quote(excerpt):
            return value, []
        matched, plausible = {}, {}
        for table in page.tables:
            for row in table.rows:
                cells = [str(c).strip() for c in row.cells if c and str(c).strip()]
                labels = [c for c in cells if parse_number(c) is None]
                numbers = [c for c in cells if parse_number(c) is not None]
                if not labels or not numbers or not all(normalize_quote(c) in quoted for c in labels):
                    continue
                if not any(normalize_quote(c) in quoted for c in numbers):
                    continue
                key = tuple(normalize_quote(c) for c in labels)
                plausible.setdefault(key, set()).add(table.table_id)
                if row.alignment_status == 'resolved' and _quoted_complete_row(cells, quoted):
                    matched.setdefault(key, {})[table.table_id] = table
        for key, tables in matched.items():
            if len(tables) != 1 or plausible[key] != set(tables):
                continue
            table = next(iter(tables.values()))
            header = _literal_header(table, page, excerpt)
            if header is None or any(q['page'] == page.page_number
                    and normalize_quote(header) in normalize_quote(q['text']) for q in [*evidence, *additions]):
                continue
            additions.append({'page': page.page_number, 'text': header})
            bindings.append({'page': page.page_number, 'table_id': table.table_id,
                             'header_text': header, 'basis': 'complete_ordered_literal_row'})
    if not additions or len(evidence) + len(additions) > 4:
        return value, []
    bound = deepcopy(value)
    bound['evidence'].extend(additions)
    return bound, bindings


def bind_brief_headers(value, result, excerpts):
    bound, audit = deepcopy(value), []
    for i, item in enumerate(bound.get('items', [])):
        bound['items'][i], bindings = bind_table_headers(item, result, excerpts)
        audit.extend(dict(item_index=i, **binding) for binding in bindings)
    return bound, audit
