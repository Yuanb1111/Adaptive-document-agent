"""Literal record-table fields and reporting periods, independent of domain."""

import re


_REPORTING_DATE = re.compile(
    r"(?i)^(?:(?:for\s+)?(?:the\s+)?(?:year|period|(?:\d+|three|six|nine|twelve)\s+months)"
    r"\s+ended|as\s+(?:of|at))\s+"
    r"(?:[A-Za-z]+\s+\d{1,2},?\s+(?:19|20)\d{2}|"
    r"\d{1,2}\s+[A-Za-z]+\s+(?:19|20)\d{2})\s*$"
)


def reporting_period_row(cells):
    """A full reporting-date row scopes every field in a record table.

    A year merely located inside a caption or a neighboring column does not.
    Return the original date for forms the existing period parser cannot type.
    """
    text = " ".join(str(cell).strip() for cell in cells if cell and str(cell).strip())
    if not _REPORTING_DATE.fullmatch(text):
        return None
    from .borderless_table_extractor import BorderlessTableExtractor
    return BorderlessTableExtractor._period_from_line(text) or text


def calendar_dimension_header(text, cells=()):
    """Calendar attributes identify records; they are not scaled amounts."""
    text = " ".join(text.split())
    from .normalizer import infer_unit_defaults
    # A literal measure unit wins. Recurring or relative time qualifiers in
    # "revenue per year" / "production last year" are not record attributes.
    if infer_unit_defaults(text).unit or re.search(
        r"(?i)\b(?:per|each|every|last|this|next|previous|prior|current)\s+(?:year|date)\b", text,
    ):
        return False
    attribute = bool(re.search(
        r"(?i)^(?:year|date)(?:\s+(?:of|when)\b|$)|"
        r"^[\w-]+\s+(?:year|date)$|(?:年份|日期)$", text,
    ))
    values = [str(value).strip() for value in cells if value and str(value).strip()
              and str(value).strip() not in {"-", "—", "–", "N/A", "Nil"}]
    return attribute and (not values or all(re.fullmatch(
        r"\d{4}(?:-\d{2}-\d{2})?|\d{1,2}[ /-]\d{1,2}[ /-]\d{4}|"
        r"[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4}", value,
    ) for value in values))


def field_labels(header_rows, width):
    """Copy aligned source wording without a reporting date or blank tiers."""
    return [" ".join(str(row[column]).strip() for row in header_rows
                     if column < len(row) and row[column] and str(row[column]).strip())
            for column in range(width)]
