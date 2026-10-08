"""Bind quoted rows to their own units and explicit calendar-date headers."""

from dataclasses import dataclass, field
from datetime import date
import re

from adaptive_document_agent.extraction.numeric_parser import parse_number
from adaptive_document_agent.extraction.normalizer import infer_unit_defaults
from .source_quotes import normalize_quote, continuous_quote_passages

_SCALES = {1: "", 1000: "thousand", 1_000_000: "million",
           1_000_000_000: "billion", 1_000_000_000_000: "trillion"}
_MONTHS = "January February March April May June July August September October November December".split()
_MONTH = "(?:" + "|".join(_MONTHS) + ")"
_DATE = re.compile(r"\b(" + _MONTH + r")\s+(\d{1,2}),?\s+((?:19|20)\d{2})\b", re.I)
_DATE_HEADER = re.compile(
    r"(?:(?:as of|for the|the|year|years|months?|ended|ending|quarter|six|three|twelve|nine)\s+)*"
    r"(" + _MONTH + r")\s+(\d{1,2})(?:,?\s+((?:19|20)\d{2}))?[,]?", re.I)
_YEAR_HEADER = re.compile(r"(?:19|20)\d{2}(?:[\s,/–-]+(?:19|20)\d{2})*")
_BASIS_START = re.compile(r"(?:/|\bper\s+)\s*", re.I)
_BASIS_WORDS = re.compile(r"[A-Za-z][\w²³-]*(?:(?:\s+|\s*/\s*)[A-Za-z][\w²³-]*)*")
_UNIT_NUMERATOR = re.compile(
    r"(?:[A-Za-z]{3}|US\$|HK\$|S\$|[$€£¥￥])\s*(?:in\s+)?"
    r"(?:thousands?|millions?|billions?|trillions?|['’]000s?)?", re.I)


def _basis_key(text):
    return re.sub(r"\s*/\s*", "/", " ".join(text.casefold().split()))


def _claim_keeps_basis(tail, basis):
    """Require the complete source denominator and a demonstrable boundary."""
    tail = tail.lstrip()
    start = _BASIS_START.match(tail)
    if not basis:
        return start is None
    if start is None:
        return False
    remainder = _basis_key(tail[start.end():])
    if not remainder.startswith(basis):
        return False
    suffix = remainder[len(basis):]
    # A slash, hyphen, or another denominator word is not a boundary. Unknown
    # prose boundaries fail closed rather than accepting a shortened unit.
    return bool(not suffix or re.match(r"^[.,;:)]|^\s+(?:in|during|as\s+of|for\s+the|"
                                      r"compared\s+with|versus|respectively)\b", suffix, re.I))


def canonical_quantity(currency, value, unit):
    """Equivalent currency/scale spellings, never currency conversion."""
    from .financial_formatter import normalize_currency_symbol
    aliases = {"k": "thousand", "m": "million", "mn": "million",
               "b": "billion", "bn": "billion", "percent": "%"}
    return normalize_currency_symbol(currency).casefold(), value, aliases.get(unit, unit)


def _number(value):
    # parse_number owns accounting signs and scale parsing. No scale conversion
    # is authorized here: retain the numeric coefficient in the quoted cell.
    return format(value, ".15g")


@dataclass
class TableQuoteContext:
    quantities: set[tuple[str, str, str]] = field(default_factory=set)
    signed_numbers: set[str] = field(default_factory=set)
    misparsed_positive_numbers: set[str] = field(default_factory=set)
    dates: set[tuple[str, str, str]] = field(default_factory=set)
    bases: dict[tuple[str, str, str], set[str]] = field(default_factory=dict)
    percentages: set[str] = field(default_factory=set)

    def numeric_claim_text(self, text):
        """Exempt complete supported dates, never authorize their digits elsewhere."""
        return _DATE.sub(lambda m: " " if (m[1].casefold(), str(int(m[2])), m[3]) in self.dates
                         else m[0], text)

    def basis_errors(self, text):
        from .executive_brief import _MONEY_QUANTITY, _QUANTITY, _quantities
        money = list(_MONEY_QUANTITY.finditer(text))
        matches = money + [m for m in _QUANTITY.finditer(text)
                           if not any(a.start() <= m.start() and m.end() <= a.end() for a in money)
                           and (m['currency'] or m['currency_suffix'] or m['unit'])]
        errors = []
        for match in matches:
            for currency, value, unit in _quantities(match[0]):
                currency, value, unit = canonical_quantity(currency, value, unit)
                relevant = [bases for (c, v, u), bases in self.bases.items()
                            if value == v and (not currency or c == currency) and (not unit or u == unit)]
                supported = set().union(*relevant) if relevant else set()
                if relevant and (len(supported) != 1 or not _claim_keeps_basis(
                        text[match.end():], next(iter(supported)))):
                    errors.append("amount changes or omits its source unit denominator")
        return errors


def _header_dates(table, source):
    month_days, years, explicit = set(), set(), set()
    for raw in table.raw_header_lines:
        line = " ".join(raw.split())
        if not line or normalize_quote(line) not in normalize_quote(source):
            continue
        match = _DATE_HEADER.fullmatch(line)
        if match:
            month_days.add((match[1].casefold(), str(int(match[2]))))
            if match[3]:
                explicit.add((match[1].casefold(), str(int(match[2])), match[3]))
        elif _YEAR_HEADER.fullmatch(line):
            years.update(re.findall(r"(?:19|20)\d{2}", line))
    # Split year columns can qualify a single shared month/day header. With
    # several date groups the text no longer proves column alignment; never
    # fabricate the Cartesian product of unrelated interim/year-end dates.
    candidates = explicit | ({(month, day, year) for month, day in month_days for year in years}
                             if len(month_days) == 1 else set())
    valid = set()
    for month, day, year in candidates:
        try:
            date(int(year), [m.casefold() for m in _MONTHS].index(month) + 1, int(day))
        except ValueError:
            continue
        valid.add((month, day, year))
    return valid


def _column_basis(table, column, source):
    from .financial_formatter import split_unit_basis
    currency = canonical_quantity(table.column_currencies[column], "", "")[0]

    def source_basis(value):
        if not value:
            return ""
        unit = infer_unit_defaults(value)
        if not unit.currency or canonical_quantity(unit.currency, "", "")[0] != currency:
            return ""  # A different currency's column cannot qualify this one.
        if not _BASIS_START.search(value):
            return ""
        if normalize_quote(value) not in normalize_quote(source):
            return None
        text = value.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1].strip()
        numerator, basis = split_unit_basis(text)
        if not _UNIT_NUMERATOR.fullmatch(numerator) or not _BASIS_WORDS.fullmatch(basis):
            return None  # Do not extract a denominator from surrounding prose.
        return _basis_key(basis)

    # Explicit column units are more specific than a table-wide default. Only
    # inspect raw header declarations when no bound metadata defines a basis.
    column_basis = source_basis(table.headers[column]) if column < len(table.headers) else ""
    if column_basis is None or column_basis:
        return column_basis
    for fields in ([table.unit_header, table.default_raw_unit], table.raw_header_lines):
        found = set()
        for value in fields:
            basis = source_basis(value)
            if basis is None:
                return None
            if basis:
                found.add(basis)
        if found:
            return next(iter(found)) if len(found) == 1 else None
    return ""


def _unit_supported(table, column, currency, scale, source, parsed):
    """A column annotation cannot supply a unit absent from the cited context."""
    if parsed.currency and parsed.raw_unit:
        return True  # Already matched the explicit cell declaration above.
    fields = [table.unit_header, table.default_raw_unit, *table.raw_header_lines]
    if column < len(table.headers):
        fields.append(table.headers[column])
    for value in fields:
        if not value or normalize_quote(value) not in normalize_quote(source):
            continue
        unit = infer_unit_defaults(value)
        if (unit.currency and canonical_quantity(unit.currency, "", "")[0] == currency
                and (unit.scale or 1) == scale):
            return True
    return False


def quoted_table_context(item, result, *, excerpts=None):
    """Return support only from a complete ordered row and one unambiguous table.

    Partial same-label rows also count as ambiguity. This prevents a shorter
    row in another table from supplying currency for a truncated quotation.
    Unit/header context must occur in the supplied excerpt for model requests.
    """
    pages = {page.page_number: page for page in result.document.pages}
    context = TableQuoteContext()
    positive_coefficients = set()
    non_percentage_coefficients = set()
    for quote in continuous_quote_passages(item.evidence, {number: p.text for number, p in pages.items()}):
        page = pages.get(quote.page)
        source = excerpts.get(quote.page, "") if excerpts is not None else (page.text if page else "")
        quoted = normalize_quote(quote.text)
        if not page or not quoted or quoted not in normalize_quote(source):
            continue
        plausible_tables, complete = set(), []
        for table in page.tables:
            for row in table.rows:
                cells = [str(cell).strip() for cell in row.cells if cell and str(cell).strip()]
                labels = [cell for cell in cells if parse_number(cell) is None]
                values = [cell for cell in cells if parse_number(cell) is not None]
                if (not labels or not values or not all(normalize_quote(label) in quoted for label in labels)
                        or not any(normalize_quote(cell) in quoted for cell in values)):
                    continue
                plausible_tables.add(table.table_id)
                if row.alignment_status == "resolved" and normalize_quote(" ".join(cells)) in quoted:
                    complete.append((table, row))
        if not complete or plausible_tables != {table.table_id for table, _ in complete}:
            continue
        if len(plausible_tables) > 1:
            # A shared total can be printed in several source tables. Accept
            # it only when the complete ordered row AND every column binding
            # agree. A partial row or a competing unit/period remains ambiguous.
            signatures = {repr((row.cells, table.column_types, table.column_currencies,
                                table.column_scales, table.column_periods,
                                table.column_audit_statuses,
                                [_column_basis(table, col, source) for col in range(len(table.column_currencies))]))
                          for table, row in complete}
            if len(signatures) != 1:
                continue
        for table, row in complete:
            context.dates.update(_header_dates(table, source))
            for column, cell in enumerate(row.cells):
                parsed = parse_number(str(cell).replace("−", "-")) if cell else None
                if parsed is None:
                    continue
                coefficient = _number(parsed.value / parsed.scale)
                if column >= len(table.column_types) or table.column_types[column] != 'percentage':
                    non_percentage_coefficients.add(coefficient)
                if (column < len(table.column_types) and table.column_types[column] == 'percentage'
                        and any(value and ('%' in value or 'percent' in value.casefold())
                                and normalize_quote(value) in normalize_quote(source)
                                for value in [*table.headers, table.default_raw_unit, *table.raw_header_lines])):
                    context.percentages.add(coefficient)
                if parsed.value < 0 and parsed.unit in {None, "currency"}:
                    context.signed_numbers.add(coefficient)
                elif parsed.unit in {None, "currency"}:
                    positive_coefficients.add(coefficient)
                if (parsed.value < 0 and parsed.unit in {None, "currency"}
                        and not str(cell).lstrip().startswith(("-", "−"))):
                    context.misparsed_positive_numbers.add(coefficient.lstrip("-"))
                if column >= len(table.column_types) or table.column_types[column] not in {"amount", "numeric"}:
                    continue
                currency = table.column_currencies[column] if column < len(table.column_currencies) else None
                scale = table.column_scales[column] if column < len(table.column_scales) else None
                if not currency or scale not in _SCALES or parsed.unit not in {None, "currency"}:
                    continue
                currency = canonical_quantity(currency, "", "")[0]
                if parsed.currency and canonical_quantity(parsed.currency, "", "")[0] != currency:
                    continue
                if parsed.raw_unit and parsed.scale != scale:
                    continue
                if not _unit_supported(table, column, currency, scale, source, parsed):
                    continue
                basis = _column_basis(table, column, source)
                if basis is None:
                    continue
                quantity = (currency, coefficient, _SCALES[scale])
                context.bases.setdefault(quantity, set()).add(basis)
    context.quantities = {q for q, bases in context.bases.items() if len(bases) == 1}
    context.misparsed_positive_numbers.difference_update(positive_coefficients)
    context.percentages.difference_update(non_percentage_coefficients)
    return context
