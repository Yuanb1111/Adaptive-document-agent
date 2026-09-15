"""Conservative table repair and cross-page continuation detection."""

from copy import deepcopy

from adaptive_document_agent.models.table import ExtractedTable, TableRow


class TableReconstructor:
    def reconstruct(self, table: ExtractedTable) -> ExtractedTable:
        repaired = deepcopy(table)
        repaired.headers = self._fill_header_blanks(repaired.headers)
        # pdfplumber already preserves multi-line text inside a cell. A row with only
        # its first cell populated is usually a section label, not a continuation.
        # Keep it separate instead of risking destructive cross-row concatenation.
        repaired.rows = [row for row in repaired.rows if any(cell for cell in row.cells)]
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
