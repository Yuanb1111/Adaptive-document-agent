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
                        bbox = tuple(float(value) for value in found.bbox)
                        context = self._context_above(page, found, distance=90)
                        default_unit, default_scale, default_currency, default_raw_unit = self._infer_defaults(raw, context)
                        table_title, unit_header = self._extract_title_and_unit(context)
                        headers, column_periods, data_rows, col_types, col_currs, col_scales = self._infer_schema_and_roles(
                            page, found, raw, default_unit, default_currency, default_scale
                        )
                        rows = self._build_table_rows(data_rows, page_number)
                        non_empty = sum(cell is not None for row in raw for cell in row)
                        density = non_empty / max(width * len(raw), 1)
                        page_tables.append(
                            ExtractedTable(
                                table_id=stable_id("table", page_number, index, bbox),
                                page=page_number,
                                headers=headers,
                                column_periods=column_periods,
                                column_types=col_types,
                                column_currencies=col_currs,
                                column_scales=col_scales,
                                table_title=table_title,
                                unit_header=unit_header,
                                rows=rows,
                                raw_cells=raw,
                                bbox=bbox,
                                confidence=max(0.35, min(0.95, density)),
                                default_unit=default_unit,
                                default_raw_unit=default_raw_unit,
                                default_unit_scale=default_scale,
                                default_currency=default_currency,
                                context_label=table_title or self._context_label(context),
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

    def _infer_schema_and_roles(
        self,
        page: object,
        found: object,
        raw: list[list[str | None]],
        default_unit: str | None,
        default_currency: str | None,
        default_scale: float | None,
    ) -> tuple[list[str], list[str | None], list[list[str | None]], list[str], list[str | None], list[float | None]]:
        headers, periods, data_rows = self._infer_schema(page, found, raw)

        # Multi-tier header detection: check if first data row is a sub-header specifying Amount vs %
        sub_role_keywords = {"amount", "%", "percent", "percentage", "share", "ratio", "multiple", "days", "count", "units", "rmb'000", "rmb", "usd", "cny", "hkd", "千元", "万元", "亿元", "元"}
        if data_rows and len(data_rows) >= 2:
            first_row = data_rows[0]
            matched_roles = [
                cell for cell in first_row[1:]
                if cell and any(kw in cell.casefold() for kw in sub_role_keywords) and not self._numeric_like(cell)
            ]
            if len(matched_roles) >= 2:
                # This is a sub-header row specifying column semantics
                for idx, cell in enumerate(first_row):
                    if cell and idx < len(headers):
                        if headers[idx].startswith("column_") or not headers[idx]:
                            headers[idx] = cell
                        elif "%" in cell or "amount" in cell.casefold():
                            headers[idx] = f"{headers[idx]} {cell}".strip()
                data_rows = data_rows[1:]

        # Classify column roles
        col_types, col_currs, col_scales = self._classify_column_roles(
            headers, periods, data_rows, default_unit, default_currency, default_scale
        )
        return headers, periods, data_rows, col_types, col_currs, col_scales

    def _infer_schema(self, page: object, found: object, raw: list[list[str | None]]) -> tuple[list[str], list[str | None], list[list[str | None]]]:
        width = len(raw[0])
        headers = ["label", *[f"column_{index + 1}" for index in range(1, width)]]
        periods: list[str | None] = [None] * width
        data_rows = raw

        # A conventional header row contains several labels, or labels plus period/year columns
        first = raw[0]
        text_cells = [cell for cell in first if cell and not self._numeric_like(cell) and cell not in {"$", "£", "€", "%"}]
        numeric_cells = [cell for cell in first if self._numeric_like(cell)]
        is_year_cell = lambda c: bool(re.search(r"(?:19|20)\d{2}", c or ""))
        is_period_header = bool(numeric_cells) and all(is_year_cell(c) for c in numeric_cells)
        later_has_numbers = any(any(self._numeric_like(cell) for cell in row[1:]) for row in raw[1:])
        if ((len(text_cells) >= 2 and not numeric_cells) or (text_cells and is_period_header)) and later_has_numbers:
            headers = [cell or f"column_{index + 1}" for index, cell in enumerate(first)]
            for index, cell in enumerate(first):
                if cell and is_year_cell(cell):
                    match = re.search(r"(?:19|20)\d{2}", cell)
                    if match:
                        periods[index] = match.group(0)
            data_rows = raw[1:]

        words = self._words_above(page, found, distance=65)
        year_lines: dict[float, list[dict[str, object]]] = {}
        for word in words:
            if re.search(r"(?:19|20)\d{2}", str(word["text"])):
                year_lines.setdefault(round(float(word["top"]), 1), []).append(word)
        year_words: list[dict[str, object]] = []
        if year_lines:
            # The closest year line is the actual table header, not narrative prose.
            year_words = year_lines[max(year_lines)]

        cells = next((row.cells for row in found.rows if any(cell is not None for cell in row.cells)), [])
        anchors = []
        for word in year_words:
            m = re.search(r"(?:19|20)\d{2}", str(word["text"]))
            if m:
                anchors.append((float(word["x0"] + word["x1"]) / 2, m.group(0)))
        for index, cell in enumerate(cells[:width]):
            if index == 0 or cell is None or not anchors or periods[index] is not None:
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

    def _classify_column_roles(
        self,
        headers: list[str],
        periods: list[str | None],
        data_rows: list[list[str | None]],
        default_unit: str | None,
        default_currency: str | None,
        default_scale: float | None,
    ) -> tuple[list[str], list[str | None], list[float | None]]:
        width = len(headers)
        col_types: list[str] = ["label"] + ["unknown"] * (width - 1)
        col_currs: list[str | None] = [None] * width
        col_scales: list[float | None] = [None] * width

        for idx in range(1, width):
            h_clean = headers[idx].casefold()
            is_nonsensical_pct = bool(re.search(r"(?i)%\s*(?:of\s*)?(?:rmb|usd|cny|hkd|eur|\$|£|€)", h_clean))
            
            # Explicit percentage header
            if ("%" in h_clean or "percent" in h_clean or "share" in h_clean or "margin" in h_clean) and not is_nonsensical_pct:
                col_types[idx] = "percentage"
                col_currs[idx] = None
                col_scales[idx] = 1.0
            elif any(term in h_clean for term in ("multiple", "times")):
                col_types[idx] = "ratio"
                col_currs[idx] = None
                col_scales[idx] = 1.0
            elif any(term in h_clean for term in ("days", "dso", "dio", "dpo")):
                col_types[idx] = "days"
                col_currs[idx] = None
                col_scales[idx] = 1.0
            elif any(term in h_clean for term in ("volume", "quantity", "units sold", "count")):
                col_types[idx] = "count"
                col_currs[idx] = None
                col_scales[idx] = 1.0
            elif any(term in h_clean for term in ("amount", "rmb", "usd", "cny", "hkd", "eur", "gbp", "'000", "thousand", "million", "金额", "千元")):
                col_types[idx] = "amount"
                col_currs[idx] = default_currency
                col_scales[idx] = default_scale
            else:
                # Inspect values across data rows for this column
                nums = [self._clean(r[idx]) for r in data_rows if idx < len(r) and r[idx]]
                pct_vals = sum(1 for v in nums if v and ("%" in v or "pct" in v.casefold()))
                if nums and pct_vals / len(nums) >= 0.5:
                    col_types[idx] = "percentage"
                    col_currs[idx] = None
                    col_scales[idx] = 1.0
                elif default_unit == "currency" or default_currency:
                    col_types[idx] = "amount"
                    col_currs[idx] = default_currency
                    col_scales[idx] = default_scale
                else:
                    col_types[idx] = default_unit or "amount"
                    col_currs[idx] = default_currency
                    col_scales[idx] = default_scale

        return col_types, col_currs, col_scales

    def _build_table_rows(self, data_rows: list[list[str | None]], page_number: int) -> list[TableRow]:
        rows: list[TableRow] = []
        for row in data_rows:
            if not row:
                continue
            cells = [cell for cell in row]
            label = cells[0] or ""
            has_other_content = any(c and c.strip() for c in cells[1:])
            is_sec = bool(label.strip()) and not has_other_content
            
            # Deduction detection ("Less:", "减：", "(Less)")
            is_ded = bool(re.search(r"(?i)^[:\-\s]*(?:less|减)[:：\s]+", label.strip()))
            
            # Subtotal detection
            is_sub = bool(re.search(r"(?i)\b(?:total|subtotal|合计|总计|小计)\b", label.strip()))
            
            # Indentation level
            leading_spaces = len(label) - len(label.lstrip(" \t\u3000"))
            indent = leading_spaces // 2 if leading_spaces else (1 if label.strip().startswith(("-", "–", "—", "•")) else 0)
            
            rows.append(
                TableRow(
                    cells=cells,
                    page=page_number,
                    indent_level=indent,
                    is_section_header=is_sec,
                    is_subtotal=is_sub,
                    is_deduction=is_ded,
                )
            )
        return rows

    def _extract_title_and_unit(self, context: str) -> tuple[str | None, str | None]:
        lines = [line.strip() for line in context.split("\n") if line.strip()]
        title: str | None = None
        unit: str | None = None
        for line in lines:
            if re.search(r"(?i)\((?:in\s+)?(?:rmb|usd|cny|hkd|eur|gbp|'000|thousands?|millions?|%)\)", line) or re.search(r"（以?人民币(?:千元|万元|亿元)?列示）", line):
                unit = line
            elif not title and len(line) >= 4 and not self._numeric_like(line):
                title = line
        return title, unit

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
            if 2 <= len(candidate) <= 100 and len(re.findall(r"[A-Za-z\u3400-\u9fff\u00c0-\u024f]", candidate)) >= 2:
                return candidate
        return None
