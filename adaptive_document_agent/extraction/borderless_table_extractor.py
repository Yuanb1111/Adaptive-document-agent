"""Fallback extraction for tables expressed by aligned text rather than borders."""

import re
from dataclasses import dataclass

from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.utils.ids import stable_id

from .normalizer import infer_unit_defaults

_VALUE = re.compile(r"(?<![A-Za-z0-9])(?:\(?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\)?%?|[—–])")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_WORD = re.compile(r"[%A-Za-z][%A-Za-z/-]*")


@dataclass(frozen=True)
class _CandidateRow:
    line_index: int
    label: str
    values: list[str]


class BorderlessTableExtractor:
    """Recognize dense, aligned numeric row runs without assuming document type."""

    def extract(self, page: object, page_number: int) -> list[ExtractedTable]:
        text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
        lines = [" ".join(line.split()) for line in text.splitlines()]
        candidates = [row for index, line in enumerate(lines) if (row := self._parse_row(index, line))]
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
            row_specs = self._rows_with_sections(group, lines, maximum_values)
            raw_rows = [cells for cells, _ in row_specs]
            context_start = max(0, (year_index if year_index is not None else group[0].line_index) - 8)
            context = " ".join(lines[context_start : group[0].line_index + 1])
            unit, scale, currency, raw_unit = self._defaults(context)
            table_id = stable_id("borderless_table", page_number, group_index, group[0].line_index, group[-1].line_index)
            context_label = self._context_label(lines, year_index if year_index is not None else group[0].line_index)
            tables.append(
                ExtractedTable(
                    table_id=table_id,
                    page=page_number,
                    headers=["label", *headers],
                    column_periods=[None, *periods],
                    rows=[TableRow(cells=cells, page=page_number, column_periods=row_periods) for cells, row_periods in row_specs],
                    raw_cells=raw_rows,
                    confidence=0.68 if years else 0.55,
                    default_unit=unit,
                    default_raw_unit=raw_unit,
                    default_unit_scale=scale,
                    default_currency=currency,
                    context_label=context_label,
                    warnings=["Recovered from aligned text because no bordered table structure was detected."],
                )
            )
        return tables

    @staticmethod
    def _parse_row(index: int, line: str) -> _CandidateRow | None:
        line = re.sub(r"(?<=[A-Za-z])\(\d+\)", "", line)
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
        elif duplicate_at is not None and re.search(r"as\s*of", context) and len(dates) >= 2:
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
        return labels

    @staticmethod
    def _headers(lines: list[str], year_index: int | None, first_row: int, width: int) -> list[str]:
        if year_index is None:
            return [f"column_{index + 2}" for index in range(width)]
        context_lines = lines[year_index + 1 : first_row]
        for line in reversed(context_lines):
            if line.startswith("("):
                continue
            words = _WORD.findall(line)
            if len(words) == width and len({word.casefold() for word in words}) < len(words):
                if any("%" in candidate for candidate in context_lines):
                    words = [word if word.casefold() in {"amount", "value"} or word.startswith("%") else f"% of {word}" for word in words]
                return words
        return [f"column_{index + 2}" for index in range(width)]

    @staticmethod
    def _rows_with_sections(group: list[_CandidateRow], lines: list[str], width: int) -> list[tuple[list[str | None], list[str | None]]]:
        output: list[tuple[list[str | None], list[str | None]]] = []
        initial_context = lines[max(0, group[0].line_index - 5) : group[0].line_index]
        active_period = next((period for line in reversed(initial_context) if (period := BorderlessTableExtractor._period_from_line(line))), None)
        previous_index = group[0].line_index - 2
        for row in group:
            between = [line.strip(" .:") for line in lines[previous_index + 1 : row.line_index] if line.strip(" .:")]
            period_updates = [period for line in between if (period := BorderlessTableExtractor._period_from_line(line))]
            if period_updates:
                active_period = period_updates[-1]
            between = [line for line in between if not BorderlessTableExtractor._period_from_line(line)]
            label = row.label
            if between and label[:1].islower():
                label = " ".join([*between, label])
            elif between and previous_index >= group[0].line_index:
                for section in between:
                    if len(section) <= 80 and len(re.findall(r"[A-Za-z]", section)) >= 2:
                        output.append(([section, *([None] * width)], [None] * (width + 1)))
            values: list[str | None] = [*row.values[:width], *([None] * max(0, width - len(row.values)))]
            row_periods = [None, *([active_period] * width)] if active_period else [None] * (width + 1)
            output.append(([label, *values], row_periods))
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
        if re.search(r"as\s*of", lowered):
            return year
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
            if len(re.findall(r"[A-Za-z]", candidate)) < 2:
                continue
            candidates.append(candidate)
        for candidate in candidates:
            if candidate.isupper() or candidate.istitle():
                return candidate
        # A non-heading fragment is still useful as an internal semantic
        # boundary between adjacent tables. Presentation decides separately
        # whether it is suitable for a user-facing title.
        return candidates[0] if candidates else None
