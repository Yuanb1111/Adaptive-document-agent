"""pdfplumber-backed table extraction with conservative confidence."""

import io
import re

from adaptive_document_agent.models.table import ExtractedTable, TableRow
from adaptive_document_agent.utils.ids import stable_id

from .borderless_table_extractor import BorderlessTableExtractor
from .normalizer import infer_unit_defaults


class TableExtractor:
    def extract(self, pdf_bytes: bytes, *, page_numbers: set[int] | None = None) -> dict[int, list[ExtractedTable]]:
        try:
            import pdfplumber
        except ImportError:
            return {}

        result: dict[int, list[ExtractedTable]] = {}
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    if page_numbers is not None and page_number not in page_numbers:
                        continue
                    page_tables: list[ExtractedTable] = []
                    found_tables = page.find_tables()
                    for index, found in enumerate(found_tables):
                        raw = [[self._clean(cell) for cell in row] for row in found.extract()]
                        if not raw:
                            continue
                        width = max(len(row) for row in raw)
                        raw = [row + [None] * (width - len(row)) for row in raw]
                        headers, column_periods, data_rows = self._infer_schema(page, found, raw)
                        rows = [TableRow(cells=row, page=page_number) for row in data_rows]
                        non_empty = sum(cell is not None for row in raw for cell in row)
                        density = non_empty / max(width * len(raw), 1)
                        bbox = tuple(float(value) for value in found.bbox)
                        context = self._context_above(page, found, distance=90)
                        default_unit, default_scale, default_currency, default_raw_unit = self._infer_defaults(raw, context)
                        page_tables.append(
                            ExtractedTable(
                                table_id=stable_id("table", page_number, index, bbox),
                                page=page_number,
                                headers=headers,
                                column_periods=column_periods,
                                rows=rows,
                                raw_cells=raw,
                                bbox=bbox,
                                confidence=max(0.35, min(0.95, density)),
                                default_unit=default_unit,
                                default_raw_unit=default_raw_unit,
                                default_unit_scale=default_scale,
                                default_currency=default_currency,
                                context_label=self._context_label(context),
                            )
                        )
                    if not page_tables:
                        page_tables.extend(BorderlessTableExtractor().extract(page, page_number))
                    result[page_number] = page_tables
        except Exception:
            return result
        return result

    @staticmethod
    def _clean(value: object) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(str(value).split())
        return cleaned or None

    def _infer_schema(self, page: object, found: object, raw: list[list[str | None]]) -> tuple[list[str], list[str | None], list[list[str | None]]]:
        width = len(raw[0])
        headers = ["label", *[f"column_{index + 1}" for index in range(1, width)]]
        periods: list[str | None] = [None] * width
        data_rows = raw

        # A conventional header row contains several labels but no numeric values.
        first = raw[0]
        text_cells = [cell for cell in first if cell and not self._numeric_like(cell) and cell not in {"$", "£", "€", "%"}]
        numeric_cells = [cell for cell in first if self._numeric_like(cell)]
        later_has_numbers = any(any(self._numeric_like(cell) for cell in row[1:]) for row in raw[1:])
        if len(text_cells) >= 2 and not numeric_cells and later_has_numbers:
            headers = [cell or f"column_{index + 1}" for index, cell in enumerate(first)]
            data_rows = raw[1:]

        words = self._words_above(page, found, distance=65)
        year_lines: dict[float, list[dict[str, object]]] = {}
        for word in words:
            if re.fullmatch(r"(?:19|20)\d{2}", str(word["text"])):
                year_lines.setdefault(round(float(word["top"]), 1), []).append(word)
        year_words: list[dict[str, object]] = []
        if year_lines:
            # The closest year line is the actual table header, not narrative prose.
            year_words = year_lines[max(year_lines)]

        cells = next((row.cells for row in found.rows if any(cell is not None for cell in row.cells)), [])
        anchors = [(float(word["x0"] + word["x1"]) / 2, str(word["text"])) for word in year_words]
        for index, cell in enumerate(cells[:width]):
            if index == 0 or cell is None or not anchors:
                continue
            center = (float(cell[0]) + float(cell[2])) / 2
            periods[index] = min(anchors, key=lambda item: abs(item[0] - center))[1]

        if year_words:
            year_top = max(float(word["top"]) for word in year_words)
            table_top = float(found.bbox[1])
            header_words = [
                word
                for word in words
                if year_top + 2 < float(word["top"]) <= table_top - 15
                and not self._numeric_like(str(word["text"]))
                and str(word["text"]) not in {"$", "£", "€", "%", "—", "–"}
            ]
            mapped: dict[int, list[dict[str, object]]] = {}
            for word in header_words:
                center = (float(word["x0"]) + float(word["x1"])) / 2
                for index, cell in enumerate(cells[:width]):
                    if cell is not None and float(cell[0]) <= center <= float(cell[2]):
                        mapped.setdefault(index, []).append(word)
                        break
            for index, assigned in mapped.items():
                if index == 0:
                    continue
                assigned.sort(key=lambda word: (float(word["top"]), float(word["x0"])))
                label = " ".join(str(word["text"]) for word in assigned)
                if label and not self._numeric_like(label):
                    headers[index] = label
        return headers, periods, data_rows

    def _words_above(self, page: object, found: object, *, distance: float) -> list[dict[str, object]]:
        left, top, right, _ = found.bbox
        return [
            word
            for word in page.extract_words(x_tolerance=2, y_tolerance=2)
            if top - distance <= float(word["top"]) < top
            and left - 5 <= float(word["x0"])
            and float(word["x1"]) <= right + 5
        ]

    def _context_above(self, page: object, found: object, *, distance: float) -> str:
        return " ".join(str(word["text"]) for word in self._words_above(page, found, distance=distance))

    @staticmethod
    def _numeric_like(value: str | None) -> bool:
        if not value:
            return False
        cleaned = value.strip().replace(",", "")
        return bool(re.fullmatch(r"\(?[+-]?(?:\d+(?:\.\d*)?|\.\d+)\)?-?", cleaned))

    @staticmethod
    def _infer_defaults(raw: list[list[str | None]], context: str) -> tuple[str | None, float | None, str | None, str | None]:
        flattened = " ".join(cell for row in raw for cell in row if cell)
        defaults = infer_unit_defaults(f"{context} {flattened}")
        if not defaults.currency:
            symbols = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "CNY"}
            currency = next((code for symbol, code in symbols.items() if any(cell == symbol for row in raw for cell in row)), None)
            if currency:
                return "currency", defaults.scale, currency, defaults.raw_unit or next(symbol for symbol, code in symbols.items() if code == currency)
        return defaults.unit, defaults.scale, defaults.currency, defaults.raw_unit

    @staticmethod
    def _context_label(context: str) -> str | None:
        candidates = [part.strip(" .:;()") for part in re.split(r"[\n.!?]", context) if part.strip(" .:;()")]
        for candidate in reversed(candidates):
            if 2 <= len(candidate) <= 100 and len(re.findall(r"[A-Za-z]", candidate)) >= 2:
                return candidate
        return None
