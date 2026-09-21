"""Fallback extraction for tables expressed by aligned text rather than borders."""

import re
from dataclasses import dataclass

from adaptive_document_agent.document_model.period_semantic_validator import format_period_label
from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.utils.ids import stable_id

from .normalizer import infer_unit_defaults
from .column_roles import explicit_percentage
from .borderless_layout import source_lines, column_anchors, align_sparse_values, geometric_headers

_VALUE = re.compile(r"(?<![A-Za-z0-9])(?:\(?[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\)?[%％]?|[—–]|-(?!\S))")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_WORD = re.compile(r"[%A-Za-z][%A-Za-z/-]*")


@dataclass(frozen=True)
class _CandidateRow:
    line_index: int
    label: str
    values: list[str]
    boxes: tuple[tuple[float, float], ...] = ()


class BorderlessTableExtractor:
    """Recognize dense, aligned numeric row runs without assuming document type."""

    def extract(self, page: object, page_number: int) -> list[ExtractedTable]:
        if hasattr(page, "extract_text"):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
        else:
            text = getattr(page, "text", "") or ""
        sources = source_lines(page, text, self._clean_line)
        lines = [self._clean_line(source.text) for source in sources]
        candidates = []
        for index, line in enumerate(lines):
            if row := self._parse_row(index, line):
                matches = list(_VALUE.finditer(sources[index].text))[-len(row.values):]
                boxes = [sources[index].bounds(m.start(), m.end()) for m in matches]
                if [m.group() for m in matches] == row.values and all(boxes):
                    row = _CandidateRow(index, row.label, row.values, tuple(boxes))
                candidates.append(row)
        groups = self._groups(candidates, lines)
        tables: list[ExtractedTable] = []
        for group_index, group in enumerate(groups):
            maximum_values = max(len(row.values) for row in group)
            year_index, years = self._nearest_year_header(lines, group[0].line_index)
            has_dot_leaders = sum("..." in lines[row.line_index] for row in group) >= 2
            if len(group) < 2 and not (years and maximum_values >= 3):
                continue
            if not years and not has_dot_leaders:
                continue
            periods = self._expand_periods(years, maximum_values, lines, year_index)
            headers = self._headers(lines, year_index, group[0].line_index, maximum_values)
            anchors = column_anchors([list(r.boxes) for r in group if len(r.values) == maximum_values], maximum_values)
            header_sources = sources[year_index+1:group[0].line_index] if year_index is not None else []
            headers = geometric_headers(header_sources, anchors, headers)
            alignments = {r.line_index: align_sparse_values(r.values, r.boxes, anchors, maximum_values)
                          for r in group if len(r.values) < maximum_values}
            row_specs = self._rows_with_sections(group, lines, maximum_values, alignments=alignments)
            raw_rows = [cells for cells, _, _ in row_specs]
            has_ambiguous_rows = any(ambiguous for _, _, ambiguous in row_specs)
            context_start = max(0, (year_index if year_index is not None else group[0].line_index) - 8)
            context = " ".join(lines[context_start : group[0].line_index + 1])
            unit, scale, currency, raw_unit = self._defaults(context)
            table_id = stable_id("borderless_table", page_number, group_index, group[0].line_index, group[-1].line_index)
            context_label = self._context_label(lines, year_index if year_index is not None else group[0].line_index)
            col_types = ["label"]
            col_currs: list[str | None] = [None]
            col_scales: list[float | None] = [None]
            for h in headers:
                h_cf = h.casefold()
                if explicit_percentage(h):
                    col_types.append("percentage")
                    col_currs.append(None)
                    col_scales.append(1.0)
                elif any(kw in h_cf for kw in ("multiple", "times")):
                    col_types.append("ratio")
                    col_currs.append(None)
                    col_scales.append(1.0)
                elif any(kw in h_cf for kw in ("days", "dso", "dio", "dpo")):
                    col_types.append("days")
                    col_currs.append(None)
                    col_scales.append(1.0)
                elif any(kw in h_cf for kw in ("volume", "quantity", "units")):
                    col_types.append("count")
                    col_currs.append(None)
                    col_scales.append(1.0)
                else:
                    col_types.append("amount")
                    col_currs.append(currency)
                    col_scales.append(scale)

            tables.append(
                ExtractedTable(
                    table_id=table_id,
                    page=page_number,
                    headers=["label", *headers],
                    column_periods=[None, *periods],
                    column_types=col_types,
                    column_currencies=col_currs,
                    column_scales=col_scales,
                    rows=[TableRow(cells=cells, page=page_number, column_periods=row_periods,
                                   alignment_status="ambiguous" if ambiguous else "resolved") for cells, row_periods, ambiguous in row_specs],
                    raw_cells=raw_rows,
                    raw_header_lines=[s.text for s in header_sources],
                    confidence=0.68 if years else 0.55,
                    default_unit=unit,
                    default_raw_unit=raw_unit,
                    default_unit_scale=scale,
                    default_currency=currency,
                    context_label=context_label,
                    warnings=["Recovered from aligned text because no bordered table structure was detected."] +
                             (["Sparse rows have ambiguous column alignment; raw cells retained but not interpreted."] if has_ambiguous_rows else []),
                )
            )
        return tables

    @staticmethod
    def _parse_row(index: int, line: str) -> _CandidateRow | None:
        line = re.sub(r"(?<=[A-Za-z])\(\d+\)", "", line)
        # A list marker preceding a word belongs to the label, not the first
        # value. Keep real minus signs, parenthesised losses and empty cells.
        line = re.sub(r"^\s*[–—•-]\s+(?=[A-Za-z\u3400-\u9fff])", "", line)
        matches = list(_VALUE.finditer(line))
        if len(matches) < 2:
            return None
        label = re.sub(r"(?:\s*\.\s*){2,}", " ", line[: matches[0].start()]).strip(" .:")
        if len(re.findall(r"[A-Za-z]", label)) < 2 or len(label) > 110:
            return None
        if BorderlessTableExtractor._period_from_line(line):
            return None
        between = line[matches[0].end() : matches[-1].start()]
        if "..." not in line and re.search(r"[A-Za-z]{2,}", between):
            return None
        values = [match.group(0) for match in matches]
        label_years = set(_YEAR.findall(label))
        value_years = [value.strip("()+-,") for value in values if _YEAR.fullmatch(value.strip("()+-,"))]
        if (
            any(value in label_years for value in value_years)
            or len(value_years) != len(set(value_years))
            or (label[:1].islower() and value_years)
        ):
            return None
        return _CandidateRow(index, label, values)

    @staticmethod
    def _clean_line(line: str) -> str:
        """Remove PDF glyph placeholders without altering reported values."""
        cleaned = re.sub(r"\s*\(cid(?::|\s)*\d+\)\s*", " ", line, flags=re.IGNORECASE)
        cleaned = re.sub(r"\ufffdC(?=\s|$)", "—", cleaned)
        return " ".join(cleaned.split())

    @staticmethod
    def _groups(candidates: list[_CandidateRow], lines: list[str]) -> list[list[_CandidateRow]]:
        groups: list[list[_CandidateRow]] = []
        for row in candidates:
            if not groups:
                groups.append([row])
                continue
            prior = groups[-1][-1]
            gap = row.line_index - prior.line_index
            intervening = lines[prior.line_index + 1 : row.line_index]
            new_year_header = any(len(_YEAR.findall(line)) >= 2 for line in intervening)
            narrative_break = any(len(line) > 115 or line.endswith(".") for line in intervening)
            if gap > 4 or new_year_header or narrative_break:
                groups.append([row])
            else:
                groups[-1].append(row)
        return groups

    @staticmethod
    def _nearest_year_header(lines: list[str], first_row: int) -> tuple[int | None, list[str]]:
        for index in range(first_row - 1, max(-1, first_row - 16), -1):
            years = _YEAR.findall(lines[index])
            if len(years) >= 2:
                return index, years
        return None, []

    @staticmethod
    def _expand_periods(years: list[str], width: int, lines: list[str], year_index: int | None) -> list[str | None]:
        if not years or width % len(years):
            return [None] * width
        context = " ".join(lines[max(0, (year_index or 0) - 3) : (year_index or 0) + 1]).casefold()
        labels = list(years)
        duplicate_at = next((index for index, year in enumerate(years) if year in years[:index]), None)
        dates = BorderlessTableExtractor._date_labels(context)
        if duplicate_at is not None and re.search(r"year\s*ended", context) and re.search(r"(three|six|nine|twelve)\s*months?", context):
            month_match = re.search(r"(three|six|nine|twelve)\s*months?", context)
            month_label = {"three": "3M", "six": "6M", "nine": "9M", "twelve": "12M"}.get(month_match.group(1), "M") if month_match else "M"
            labels = [f"FY{year}" if index < duplicate_at else f"{month_label}{year}" for index, year in enumerate(years)]
        elif duplicate_at is not None and re.search(r"as\s+(?:of|at)", context) and len(dates) >= 2:
            date_split = years.index(years[duplicate_at])
            trailing = len(years) - date_split
            later_dates = dates[-trailing:]
            base_date = dates[0]
            labels = [
                f"{year}-{base_date}" if index < date_split else f"{year}-{later_dates[index - date_split]}"
                for index, year in enumerate(years)
            ]
        elif re.search(r"year\s*ended", context):
            labels = [f"FY{year}" for year in years]
        elif month_match := re.search(r"(three|six|nine|twelve)\s*months?\s*ended", context):
            month_label = {"three": "3M", "six": "6M", "nine": "9M", "twelve": "12M"}[month_match.group(1)]
            labels = [f"{month_label}{year}" for year in years]
        repeats = width // len(labels)
        return [label for label in labels for _ in range(repeats)]

    @staticmethod
    def _date_labels(context: str) -> list[str]:
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
            "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        }
        labels: list[str] = []
        for match in re.finditer(r"\b(" + "|".join(months) + r")\s*(\d{1,2})\b", context):
            label = f"{months[match.group(1)]:02d}-{int(match.group(2)):02d}"
            if label not in labels:
                labels.append(label)
        for match in re.finditer(r"\b(\d{1,2})\s+(" + "|".join(months) + r")\b", context):
            label = f"{months[match.group(2)]:02d}-{int(match.group(1)):02d}"
            if label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _headers(lines: list[str], year_index: int | None, first_row: int, width: int) -> list[str]:
        if year_index is None:
            return [f"column_{index + 2}" for index in range(width)]
        context_lines = lines[year_index + 1 : first_row]
        years = _YEAR.findall(lines[year_index])
        if years and width % len(years) == 0:
            measure_count = width // len(years)
            repeated_phrases = [
                phrase
                for line in context_lines
                if not line.startswith("(") and (phrase := BorderlessTableExtractor._phrase_repeated(line, len(years)))
            ]
            repeated_phrases = list(dict.fromkeys(repeated_phrases))
            if (
                len(repeated_phrases) == measure_count
                and all(len(_WORD.findall(phrase)) >= 2 for phrase in repeated_phrases)
                and any(left.casefold() in right.casefold() for left in repeated_phrases for right in repeated_phrases if left != right)
            ):
                return [phrase for _ in years for phrase in repeated_phrases]
        # Reassemble full-width tiers without propagating a nearby '%' across
        # the table. E.g. 'Gross profit ...' / 'profit margin ...' are separate
        # fragments in each numeric column, not global percentage declarations.
        tiers = [_WORD.findall(line) for line in context_lines if not line.startswith("(")
                 and not re.fullmatch(r"(?:%\s*of\s*)+", line, re.I)]
        tiers = [words for words in tiers if len(words) == width and len({w.casefold() for w in words}) < width]
        if len(tiers) >= 2:
            return [" ".join(dict.fromkeys(words[i] for words in tiers)) for i in range(width)]
        for line in reversed(context_lines):
            if line.startswith("("):
                continue
            words = _WORD.findall(line)
            if len(words) == width and len({word.casefold() for word in words}) < len(words):
                # This is a confirmed Amount/% structure: repeated '% of'
                # fragments and explicitly labelled Amount columns. A general
                # '(except percentages)' unit note is NOT column evidence.
                prefix_count = max((len(re.findall(r"%\s*of\b", candidate, re.I)) for candidate in context_lines), default=0)
                if (years and width == 2*len(years) and prefix_count == len(years)
                        and all(words[i].casefold() in {"amount", "value"} for i in range(0, width, 2))):
                    words = [word if i % 2 == 0 or word.startswith("%") else f"% of {word}" for i, word in enumerate(words)]
                return words
        # An explicit row of per-column units is sufficient even when semantic
        # header fragments cannot be safely reassembled.
        for line in context_lines:
            unit_cells = re.findall(r"\((?:RMB|CNY|USD|HKD|EUR|GBP|%|％)\)", line, re.I)
            if len(unit_cells) == width and "".join(line.split()) == "".join(unit_cells):
                return ["%" if "%" in cell or "％" in cell else "Amount" for cell in unit_cells]
        return [f"column_{index + 2}" for index in range(width)]

    @staticmethod
    def _phrase_repeated(line: str, repeats: int) -> str | None:
        words = _WORD.findall(line)
        if repeats < 2 or not words or len(words) % repeats:
            return None
        size = len(words) // repeats
        chunks = [words[index * size : (index + 1) * size] for index in range(repeats)]
        if any([word.casefold() for word in chunk] != [word.casefold() for word in chunks[0]] for chunk in chunks[1:]):
            return None
        return " ".join(chunks[0])

    @staticmethod
    def _rows_with_sections(group: list[_CandidateRow], lines: list[str], width: int, *, alignments=None) -> list[tuple[list[str | None], list[str | None], bool]]:
        output: list[tuple[list[str | None], list[str | None], bool]] = []
        initial_context = lines[max(0, group[0].line_index - 5) : group[0].line_index]
        active_period = next((period for line in reversed(initial_context) if (period := BorderlessTableExtractor._period_from_line(line))), None)
        previous_index = group[0].line_index - 2
        for row in group:
            between = [line.strip(" .:") for line in lines[previous_index + 1 : row.line_index] if line.strip(" .:")]
            period_updates = [period for line in between if (period := BorderlessTableExtractor._period_from_line(line))]
            if period_updates:
                active_period = period_updates[-1]
            between = [line for line in between if not BorderlessTableExtractor._period_from_line(line)
                       and sum(bool(re.search(r"\d", m.group())) for m in _VALUE.finditer(line)) < 2]
            label = row.label
            if between and label[:1].islower():
                label = " ".join([*between, label])
            elif between and previous_index >= group[0].line_index:
                for section in between:
                    if len(section) <= 80 and len(re.findall(r"[A-Za-z]", section)) >= 2:
                        output.append(([section, *([None] * width)], [None] * (width + 1), False))
            values: list[str | None] = [*row.values[:width], *([None] * max(0, width - len(row.values)))]
            if alignments and alignments.get(row.line_index) is not None:
                values = alignments[row.line_index]
            row_periods = [None, *([active_period] * width)] if active_period else [None] * (width + 1)
            ambiguous = bool(alignments is not None and row.line_index in alignments and alignments[row.line_index] is None)
            output.append(([label, *values], row_periods, ambiguous))
            previous_index = row.line_index
        return output

    @staticmethod
    def _period_from_line(line: str) -> str | None:
        years = _YEAR.findall(line)
        if len(years) != 1:
            return None
        lowered = line.casefold()
        year = years[0]
        if re.search(r"year\s*ended", lowered):
            return f"FY{year}"
        if month_match := re.search(r"(three|six|nine|twelve)\s*months?\s*ended", lowered):
            label = {"three": "3M", "six": "6M", "nine": "9M", "twelve": "12M"}[month_match.group(1)]
            return f"{label}{year}"
        if re.search(r"as\s+(?:of|at)", lowered):
            formatted = format_period_label(line, is_balance_sheet=True)
            # A bare year is insufficient for a point-in-time label. Preserve
            # uncertainty instead of turning it into an FY period downstream.
            return formatted if re.search(r"\b\d{1,2}\s+[A-Za-z]{3}\s+20\d{2}\*?$", formatted) else None
        return None

    @staticmethod
    def _defaults(context: str) -> tuple[str | None, float | None, str | None, str | None]:
        defaults = infer_unit_defaults(context)
        return defaults.unit, defaults.scale, defaults.currency, defaults.raw_unit

    @staticmethod
    def _context_label(lines: list[str], header_index: int) -> str | None:
        candidates: list[str] = []
        for raw in reversed(lines[max(0, header_index - 24) : header_index]):
            candidate = raw.strip(" .:;()")
            lowered = candidate.casefold()
            if not candidate or len(candidate) > 100 or candidate.endswith("."):
                continue
            if re.search(r"year\s*ended|months?\s*ended|as\s*of", lowered):
                continue
            if sum(bool(re.search(r"\d", m.group())) for m in _VALUE.finditer(candidate)) >= 2:
                continue
            if len(re.findall(r"[A-Za-z]", candidate)) < 2:
                continue
            candidates.append(candidate)
        for candidate in candidates:
            words = candidate.split()
            heading_case = bool(words) and all(w[:1].isupper() or w.casefold() in {"and", "of", "the", "by", "in", "for", "to", "&"} for w in words)
            if candidate.isupper() or heading_case:
                return candidate
        # A non-heading fragment is still useful as an internal semantic
        # boundary between adjacent tables. Presentation decides separately
        # whether it is suitable for a user-facing title.
        return candidates[0] if candidates else None
