import re
from copy import deepcopy
from typing import Any

from adaptive_document_agent.extraction.numeric_parser import parse_number
from adaptive_document_agent.models.table import ExtractedTable
from .column_roles import percentage_column

_YEAR_OR_PERIOD_PATTERN = re.compile(
    r"\b(?:19|20)\d{2}\b"
    r"|(?:FY\s*)?(?:19|20)\d{2}"
    r"|(?:3M|6M|9M|12M|Q[1-4]|1H|2H)\s*(?:19|20)?\d{2}"
    r"|(?:19|20)\d{2}\s*年(?:度)?"
)

_SUPER_HEADER_DESCRIPTORS = re.compile(
    r"^(?:for\s+the\s+)?(?:year|period|three\s+months|six\s+months|nine\s+months)\s+ended"
    r"|^as\s+(?:of|at)\b"
    r"|^(?:item|particulars|line\s+item|description|metrics?|segment|category|项目|类别)\b"
    r"|截至.*?(?:止年度|止期间)",
    flags=re.IGNORECASE,
)

_SUB_ROLE_PERCENTAGE_KEYWORDS = (
    "%", "percent", "percentage", "share", "margin", "占比", "份额", "比例", "毛利率", "利润率", "rate"
)
_SUB_ROLE_AMOUNT_KEYWORDS = (
    "amount", "金额", "rmb'000", "rmb", "usd", "cny", "hkd", "eur", "gbp", "千元", "万元", "亿元", "元", "'000", "thousand", "million", "$", "£", "€", "¥"
)
_SUB_ROLE_DAYS_KEYWORDS = ("days", "dso", "dio", "dpo", "天")
_SUB_ROLE_RATIO_KEYWORDS = ("multiple", "times", "倍")
_SUB_ROLE_COUNT_KEYWORDS = ("volume", "quantity", "units", "数量", "销量", "出货量", "台", "件", "套")


def _is_data_number(val: str | None) -> bool:
    if not val:
        return False
    cleaned = val.strip().replace(",", "")
    if _YEAR_OR_PERIOD_PATTERN.fullmatch(cleaned):
        return False
    if cleaned in {"$", "£", "€", "%", "—", "–", "-"}:
        return False
    return bool(parse_number(val))


class TableReconstructor:
    @classmethod
    def detect_header_row_count(cls, raw: list[list[str | None]]) -> int:
        """Identify how many rows from the top of the table serve as multi-level headers."""
        if not raw:
            return 0
        max_scan = min(4, len(raw))
        first_data_idx = -1
        for idx in range(max_scan):
            row = raw[idx]
            if not row:
                continue
            first_cell = (row[0] or "").strip()
            other_cells = row[1:]
            data_num_count = sum(1 for c in other_cells if _is_data_number(c))

            is_descriptor = bool(_SUPER_HEADER_DESCRIPTORS.search(first_cell))
            is_year_row = any(_YEAR_OR_PERIOD_PATTERN.search(c or "") for c in other_cells) and data_num_count == 0
            is_role_row = any(
                any(kw in (c or "").casefold() for kw in _SUB_ROLE_PERCENTAGE_KEYWORDS + _SUB_ROLE_AMOUNT_KEYWORDS)
                for c in other_cells
            ) and data_num_count == 0

            if data_num_count >= 2 and not is_descriptor and not is_year_row and not is_role_row:
                first_data_idx = idx
                break

        if first_data_idx == -1:
            if len(raw) >= 2:
                row0_years = any(_YEAR_OR_PERIOD_PATTERN.search(c or "") for c in raw[0][1:])
                row1_roles = any(
                    any(kw in (c or "").casefold() for kw in _SUB_ROLE_PERCENTAGE_KEYWORDS + _SUB_ROLE_AMOUNT_KEYWORDS)
                    for c in raw[1][1:]
                )
                if row0_years and row1_roles:
                    return 2
            return 1
        return max(1, first_data_idx)

    @classmethod
    def reconstruct_multi_tier_headers(
        cls,
        raw: list[list[str | None]],
        *,
        default_unit: str | None = None,
        default_currency: str | None = None,
        default_scale: float | None = None,
        context: str = "",
        existing_periods: list[str | None] | None = None,
    ) -> tuple[list[str], list[str | None], list[list[str | None]], list[str], list[str | None], list[float | None]]:
        """Extract multi-tier headers, periods, and column semantic roles from raw table grid."""
        if not raw:
            return [], [], [], [], [], []
        width = max(len(r) for r in raw)
        if width < 2:
            headers = ["label"] + [f"column_{i + 1}" for i in range(1, width)]
            return headers, [None] * width, raw, ["label"] + ["unknown"] * (width - 1), [None] * width, [None] * width

        num_headers = cls.detect_header_row_count(raw)
        header_rows = raw[:num_headers]
        data_rows = raw[num_headers:]

        periods: list[str | None] = [None] * width
        if existing_periods:
            for i, p in enumerate(existing_periods[:width]):
                if p:
                    periods[i] = p

        # 1. Period extraction and column-span propagation
        for hr in header_rows:
            anchors: list[tuple[int, str]] = []
            for c in range(1, width):
                if c < len(hr) and hr[c]:
                    val = hr[c].strip()
                    m = _YEAR_OR_PERIOD_PATTERN.search(val)
                    if m:
                        anchors.append((c, m.group(0)))

            if len(anchors) >= 2 or (len(anchors) == 1 and not any(periods)):
                for k, (start_col, p_val) in enumerate(anchors):
                    next_start = anchors[k + 1][0] if k + 1 < len(anchors) else width
                    for c in range(start_col, next_start):
                        if periods[c] is None:
                            periods[c] = p_val

        # 2. Column role / measure type classification
        col_types: list[str] = ["label"] + ["unknown"] * (width - 1)
        col_currs: list[str | None] = [None] * width
        col_scales: list[float | None] = [None] * width
        sub_labels: list[str | None] = [None] * width

        for c in range(1, width):
            tokens: list[str] = []
            for hr in header_rows:
                if c < len(hr) and hr[c]:
                    txt = hr[c].strip()
                    if not _YEAR_OR_PERIOD_PATTERN.fullmatch(txt):
                        tokens.append(txt)

            combined_txt = " ".join(tokens).casefold()

            col_data_cells = [dr[c] for dr in data_rows if c < len(dr)]
            is_pct = percentage_column(combined_txt, col_data_cells)
            is_ratio = any(kw in combined_txt for kw in _SUB_ROLE_RATIO_KEYWORDS)
            is_days = any(kw in combined_txt for kw in _SUB_ROLE_DAYS_KEYWORDS)
            is_count = any(kw in combined_txt for kw in _SUB_ROLE_COUNT_KEYWORDS)
            is_amount = any(kw in combined_txt for kw in _SUB_ROLE_AMOUNT_KEYWORDS)

            if is_pct:
                col_types[c] = "percentage"
                col_currs[c] = None
                col_scales[c] = 1.0
                sub_labels[c] = "%"
            elif is_ratio:
                col_types[c] = "ratio"
                col_currs[c] = None
                col_scales[c] = 1.0
                sub_labels[c] = "x"
            elif is_days:
                col_types[c] = "days"
                col_currs[c] = None
                col_scales[c] = 1.0
                sub_labels[c] = "days"
            elif is_count:
                col_types[c] = "count"
                col_currs[c] = None
                col_scales[c] = 1.0
                sub_labels[c] = "units"
            elif is_amount:
                col_types[c] = "amount"
                col_currs[c] = default_currency
                col_scales[c] = default_scale
                sub_labels[c] = "Amount"
            else:
                if default_unit == "currency" or default_currency:
                    col_types[c] = "amount"
                    col_currs[c] = default_currency
                    col_scales[c] = default_scale
                    sub_labels[c] = "Amount"
                else:
                    col_types[c] = default_unit or "amount"
                    col_currs[c] = default_currency
                    col_scales[c] = default_scale
                    sub_labels[c] = default_unit or "Amount"

        # 3. Construct headers
        headers = ["label"] + [f"column_{i + 1}" for i in range(1, width)]
        if header_rows and header_rows[0] and header_rows[0][0]:
            first_label = header_rows[0][0].strip()
            if first_label and not _SUPER_HEADER_DESCRIPTORS.search(first_label):
                headers[0] = first_label

        for c in range(1, width):
            p = periods[c]
            sub = sub_labels[c]
            if p and sub:
                headers[c] = f"{p} {sub}"
            elif p:
                headers[c] = p
            elif sub:
                headers[c] = sub

        return headers, periods, data_rows, col_types, col_currs, col_scales

    def reconstruct(self, table: ExtractedTable) -> ExtractedTable:
        repaired = deepcopy(table)
        repaired.headers = self._fill_header_blanks(repaired.headers)
        repaired.rows = [row for row in repaired.rows if any(cell for cell in row.cells)]

        raw_has_header = bool(repaired.raw_cells) and not any(
            _is_data_number(cell) for cell in repaired.raw_cells[0][1:]
        )
        if raw_has_header and (
            not any(repaired.column_periods)
            or None in repaired.column_periods[1:]
            or not repaired.column_types
            or any(t in {"unknown", "percentage"} for t in repaired.column_types[1:])
        ):
            headers, periods, data_rows, col_types, col_currs, col_scales = self.reconstruct_multi_tier_headers(
                repaired.raw_cells,
                default_unit=repaired.default_unit,
                default_currency=repaired.default_currency,
                default_scale=repaired.default_unit_scale,
                context=repaired.context_label or "",
                existing_periods=repaired.column_periods,
            )
            if any(periods):
                if any(old == "percentage" and new != "percentage" for old, new in zip(repaired.column_types, col_types)):
                    repaired.warnings.append("Re-evaluated percentage column roles against original headers and cells.")
                repaired.headers = headers
                repaired.column_periods = periods
                repaired.column_types = col_types
                repaired.column_currencies = col_currs
                repaired.column_scales = col_scales
                # raw_cells may describe only the first page of a combined
                # table. Never replace evidence-bearing continuation rows with
                # that first-page grid when re-evaluating column roles.
                for header_row in repaired.raw_cells[:len(repaired.raw_cells) - len(data_rows)]:
                    if repaired.rows and repaired.rows[0].cells == header_row:
                        repaired.rows.pop(0)
                for row in repaired.rows:
                    if not any(row.column_periods) and any(periods):
                        row.column_periods = periods
        return repaired

    def combine_continuations(self, tables: list[ExtractedTable]) -> list[ExtractedTable]:
        if not tables:
            return []
        ordered = sorted((self.reconstruct(table) for table in tables), key=lambda table: (table.page, table.table_id))
        combined: list[ExtractedTable] = []
        for table in ordered:
            if combined and self._compatible(combined[-1], table):
                parent = combined[-1]
                parent.rows.extend(table.rows)
                parent.context_label = parent.context_label or table.context_label
                parent.continues_as = table.table_id
                table.continued_from = parent.table_id
                parent.confidence = min(parent.confidence, table.confidence) * 0.95
                parent.warnings.append(f"Combined with compatible continuation on page {table.page}.")
            else:
                combined.append(table)
        return combined

    @staticmethod
    def _fill_header_blanks(headers: list[str]) -> list[str]:
        output: list[str] = []
        for index, header in enumerate(headers):
            clean = " ".join(header.split())
            output.append(clean or f"column_{index + 1}")
        return output

    @staticmethod
    def _compatible(left: ExtractedTable, right: ExtractedTable) -> bool:
        if right.page != left.page + 1 or len(left.headers) != len(right.headers):
            return False
        left_periods = [period for period in left.column_periods if period]
        right_periods = [period for period in right.column_periods if period]
        if left_periods and right_periods and left_periods != right_periods:
            return False
        normalize = lambda value: "".join(character.lower() for character in value if character.isalnum())
        if left.context_label and right.context_label and normalize(left.context_label) != normalize(right.context_label):
            return False
        matching = sum(normalize(a) == normalize(b) for a, b in zip(left.headers, right.headers, strict=True))
        return matching / max(len(left.headers), 1) >= 0.75
