"""Keep analytical column metadata within a provable literal header scope.

Source grids remain untouched. Captions and chart annotations are not column
headers merely because a ruling happened to surround the whole source figure.
"""

import re

from adaptive_document_agent.models import SourceEvidence, ValidationIssue
from .column_roles import explicit_percentage
from .numeric_parser import parse_number


_YEAR = r"(?:19|20)\d{2}"
_PERIOD_CELL = re.compile(
    rf"(?i)(?:FY\s*)?{_YEAR}E?|(?:[1-9]|1[0-2])M\s*{_YEAR}|"
    rf"(?:Q[1-4]|[12]H)\s*{_YEAR}|{_YEAR}-\d{{2}}-\d{{2}}|"
    rf"(?:CAGR\s+)?{_YEAR}\s*[-–—]\s*{_YEAR}E?"
)
_YEAR_TOKEN = re.compile(rf"\b{_YEAR}E?\b",re.IGNORECASE)
_UNIT_CELL = re.compile(
    r"(?i)(?:amount|percent(?:age)?|[%％]|ratio|times|days|count|units|"
    r"(?:RMB|CNY|USD|HKD|EUR|GBP|US\$|HK\$|[$£€¥])"
    r"(?:\s*(?:in\s*)?(?:['’]?000|thousands?|millions?|billions?))?)"
)
_WARNING = "Analytical column headers are unresolved: "


def _role_tier(row):
    from .table_reconstructor import (
        _SUB_ROLE_AMOUNT_KEYWORDS, _SUB_ROLE_COUNT_KEYWORDS,
        _SUB_ROLE_DAYS_KEYWORDS, _SUB_ROLE_RATIO_KEYWORDS,
    )
    role_terms=(*_SUB_ROLE_AMOUNT_KEYWORDS,*_SUB_ROLE_COUNT_KEYWORDS,
                *_SUB_ROLE_DAYS_KEYWORDS,*_SUB_ROLE_RATIO_KEYWORDS)
    cells=[str(cell).strip() for cell in row[1:] if cell and str(cell).strip()]
    return bool(cells) and all(
        _UNIT_CELL.fullmatch(cell) or (not re.search(r"\d",cell) and (
            explicit_percentage(cell) or any(term in cell.casefold() for term in role_terms)
        )) for cell in cells)


def scoped_source_headers(header, width, *, original_header=None, source_spans=(), body_rows=()):
    """Return safe semantic tiers, exact period overrides, and a quarantine reason."""
    candidates = []
    for index, row in enumerate(header):
        cells = [(column, str(cell).strip()) for column, cell in enumerate(row[1:], 1)
                 if cell and str(cell).strip()]
        source_row=original_header[index] if original_header is not None else row
        source_ranges=sum(bool(cell and _PERIOD_CELL.fullmatch(str(cell).strip())
                               and len(_YEAR_TOKEN.findall(str(cell)))>1)
                          for cell in source_row[1:])
        has_range=any(len(_YEAR_TOKEN.findall(cell))>1 for _,cell in cells)
        explicit_range_group=(source_ranges==1 and cells
            and any(r==index and start==cells[0][0] and end==cells[-1][0]
                    for r,start,end in source_spans)
            and any(len(row)>=width and all(row[1:width]) and _role_tier(row)
                    for row in header[index+1:]))
        if (cells
                and all(_PERIOD_CELL.fullmatch(cell) for _, cell in cells)
                and (not has_range or source_ranges>=min(2,width-1) or explicit_range_group)):
            candidates.append((index, cells))
    if candidates:
        index, cells = candidates[-1]
        # A leaf year row supersedes a title's date range and numeric chart
        # annotations. Explicit unit-only tiers above it still apply.
        units = [row for row in header[:index] if _role_tier(row)]
        # Only literal cells or already expanded source-geometry spans establish
        # a period. A blank neighboring cell does not prove a shared year.
        periods = dict(cells)
        if any(column not in periods and any(column<len(row) and parse_number(row[column])
                for row in body_rows)
               for column in range(1,width)):
            return header, {}, "a numeric source column has no aligned period or measure header"
        return [*units, *header[index:]], periods, None
    numeric_columns=sum(any(column<len(row) and parse_number(row[column]) for row in body_rows)
                        for column in range(1,width))
    if numeric_columns > 1 and not any(any(cell for cell in row) for row in header):
        return header, {}, "multiple value columns have no retained source header alignment"
    if any(len(_YEAR_TOKEN.findall(str(cell or ""))) > 1
           for row in header for cell in row[1:]):
        return header, {}, "multiple period endpoints share a source cell without aligned column headers"
    return header, {}, None


def quarantine_header_rows(table, reason):
    # Leave no guessed year or measure role on the quarantined analytical copy.
    width=len(table.headers)
    table.headers=["label",*[f"column_{column + 1}" for column in range(1,width)]]
    table.column_periods=[None]*width
    table.column_types=["label",*["unknown"]*(width-1)]
    table.column_currencies=[None]*width
    table.column_scales=[None]*width
    for row in table.rows:
        row.alignment_status = "ambiguous"
    warning = _WARNING + reason + "; raw source cells are retained without analytical interpretation."
    if warning not in table.warnings:
        table.warnings.append(warning)
    return table


def source_header_issues(document):
    """Expose quarantined extraction data in the normal result diagnostics."""
    return [ValidationIssue(
        code="ambiguous_source_table_header", stage="extraction", severity="warning",
        message=warning, related_ids=[table.table_id],
        evidence=[SourceEvidence(page=table.page, table_id=table.table_id,
                                 extraction_method="digital_table", confidence=table.confidence)],
    ) for page in document.pages for table in page.tables for warning in table.warnings
        if warning.startswith(_WARNING)]


def explicit_caption_key(table):
    """A conflicting literal caption prevents treating a new table as continuation."""
    if table.table_title:
        title=re.sub(r"(?i)\b(?:continued|cont[.]?)\b|\(continued\)", "", table.table_title)
        return " ".join(re.findall(r"[^\W_]+",title,re.UNICODE)).casefold()
    for text in table.raw_header_lines:
        if not text:
            continue
        text = re.sub(r"(?i)\b(?:continued|cont[.]?)\b|\(continued\)", "", text)
        words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
        long_unicode=any(ord(char)>127 and char.isalpha() for char in text) and sum(
            char.isalpha() for char in text)>=12
        if ((len(words) >= 4 or long_unicode) and not re.match(
                r"(?i)^(?:(?:for\s+the\s+)?(?:year|period|three|six|nine|twelve)\b|"
                r"as\s+(?:of|at)\b|CAGR\b|截至|截至於)", text.strip())
                and not _PERIOD_CELL.fullmatch(text.strip())
                and not re.search(r"[%％]", text)):
            return " ".join(re.findall(r"[^\W_]+",text,re.UNICODE)).casefold()
    return None
