"""Deterministic table/text observations before semantic enrichment."""

import re

from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
from adaptive_document_agent.document_model.period_semantic_validator import classify_period
from adaptive_document_agent.models import Observation, ParsedDocument, SourceEvidence
from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.utils.ids import stable_id

from .numeric_parser import parse_number

_PERIOD = re.compile(r"(?i)^(?:FY\s*)?(?:19|20)\d{2}$|^Q[1-4]\s*(?:19|20)?\d{2}$")
_GENERIC_LABELS = {"total", "current", "deferred", "other", "net", "subtotal", "amount", "value"}


class ObservationExtractor:
    def extract(
        self,
        document: ParsedDocument,
        *,
        required_metrics: set[str] | None = None,
        page_ranges: list[tuple[int, int]] | None = None,
    ) -> list[Observation]:
        observations: list[Observation] = []
        for page in document.pages:
            if page_ranges and not any(start <= page.page_number <= end for start, end in page_ranges):
                continue
            for table in page.tables:
                observations.extend(self._table_observations(table))
            observations.extend(self._text_observations(page.page_number, page.text))
        if required_metrics:
            wanted = {metric.casefold() for metric in required_metrics}
            observations = [item for item in observations if item.metric_original.casefold() in wanted or (item.metric_canonical or "").casefold() in wanted]
        return observations

    def _table_observations(self, table: ExtractedTable) -> list[Observation]:
        if len(table.headers) < 2 or not table.rows:
            return []
        output: list[Observation] = []
        meaningful_header_list = [
            header
            for header in table.headers[1:]
            if self._meaningful_header(header)
        ]
        column_metric_mode = len(set(meaningful_header_list)) >= 2
        current_section: str | None = None
        for row_index, row in enumerate(table.rows):
            if not row.cells:
                continue
            label = self._row_label(row.cells[0])
            numeric_columns = [column for column, raw in enumerate(row.cells[1:], start=1) if raw and parse_number(raw)]
            if label and not numeric_columns:
                current_section = label.rstrip(":")
                continue
            if not label:
                continue
            for column in numeric_columns:
                header = table.headers[column] if column < len(table.headers) else f"column_{column + 1}"
                row_period = row.column_periods[column] if column < len(row.column_periods) else None
                table_period = table.column_periods[column] if column < len(table.column_periods) else None
                period = row_period or table_period
                if (any(table.column_periods) or any(row.column_periods)) and not period and not self._meaningful_header(header):
                    continue
                if column_metric_mode and self._meaningful_header(header):
                    metric = f"{current_section}: {header}" if current_section else header
                    dimensions = {table.headers[0] if self._meaningful_header(table.headers[0]) else "category": label}
                else:
                    metric = f"{label}: {header}" if self._meaningful_header(header) else label
                    dimensions = {"section": current_section} if current_section else {}
                if period and re.match(r"^(FY|3M|6M|9M|12M)", period):
                    dimensions["period_basis"] = re.match(r"^(FY|3M|6M|9M|12M)", period).group(1)  # type: ignore[union-attr]
                if table.context_label:
                    dimensions["table_context"] = table.context_label
                item = self._make(
                    table,
                    row_index,
                    metric,
                    row.cells[column],
                    period=period,
                    dimensions=dimensions,
                    column_label=header,
                    column=column,
                )
                if item:
                    output.append(item)
        return output

    def _make(self, table: ExtractedTable, row_index: int, metric: str, raw: str | None, *, period: str | None = None, dimensions: dict[str, str] | None = None, column_label: str | None = None, column: int | None = None) -> Observation | None:
        if raw is None or not (number := parse_number(raw)):
            return None
        unit, currency = number.unit, number.currency
        scale = number.scale
        value = number.value
        if column is not None:
            adjacent = {
                adjacent_value
                for index in (column - 1, column + 1)
                if 0 <= index < len(table.rows[row_index].cells)
                and (adjacent_value := table.rows[row_index].cells[index])
            }
            if "$" in adjacent:
                unit, currency = "currency", "USD"
            elif "£" in adjacent:
                unit, currency = "currency", "GBP"
            elif "€" in adjacent:
                unit, currency = "currency", "EUR"
            elif "%" in adjacent and (number.value is not None and abs(number.value) <= 100 and table.default_unit != "currency"):
                unit = "percent"
        header_lower = (column_label or "").casefold()
        is_nonsensical_pct_header = bool(re.search(r"(?i)%\s*(?:of\s*)?(?:rmb|usd|cny|hkd|eur|\$|£|€)", header_lower))
        if ("%" in header_lower or "percent" in header_lower) and not is_nonsensical_pct_header:
            unit, currency, scale = "percent", None, 1.0
            value = number.value
        elif any(term in header_lower for term in ("volume", "quantity", "units sold", "count")):
            unit, currency, scale = "count", None, 1.0
            value = number.value
        else:
            unit = unit or table.default_unit
            currency = currency or table.default_currency
            if scale == 1.0 and table.default_unit_scale:
                scale = table.default_unit_scale
                value *= scale
        confidence = min(table.confidence, number.confidence, 0.9 if period else 0.75)
        evidence = SourceEvidence(
            page=table.rows[row_index].page,
            text=raw,
            table_id=table.table_id,
            row_label=metric if period else table.rows[row_index].cells[0],
            column_label=column_label,
            extraction_method="digital_table",
            confidence=confidence,
        )
        semantic = classify_metric(
            metric,
            value=value,
            raw_unit=number.raw_unit or table.default_raw_unit,
            unit=unit,
        )
        if semantic.is_multiple:
            unit = "multiple"
            currency = None
            scale = 1.0
            value = number.value
        elif semantic.is_currency:
            unit = "currency"
            currency = currency or table.default_currency
        elif semantic.is_percentage:
            unit = "percent"
            currency = None
            scale = 1.0
            value = number.value

        is_bs = semantic.is_currency and any(
            term in metric.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor", "asset", "equity")
        )
        period_sem = classify_period(period, is_balance_sheet=is_bs)

        return Observation(
            id=stable_id("observation", table.table_id, row_index, column, column_label, period, raw),
            metric_original=metric,
            value=value,
            raw_value=raw,
            unit=unit,
            raw_unit=number.raw_unit or table.default_raw_unit,
            unit_scale=scale,
            currency=currency,
            period=period,
            dimensions=dimensions or {},
            evidence=[evidence],
            confidence=confidence,
            semantic_type=semantic.semantic_type,
            unit_family=semantic.unit_family,
            display_unit=semantic.display_unit,
            period_type=period_sem.period_type,
            as_of_date=period_sem.clean_label if is_bs and period_sem.is_interim else None,
            audited_status="unaudited" if period_sem.is_unaudited else "audited",
        )

    @staticmethod
    def _row_label(value: str | None) -> str | None:
        if not value:
            return None
        label = " ".join(value.split()).strip()
        if parse_number(label) or label in {"$", "£", "€", "%", "—", "–", "-"}:
            return None
        if len(re.findall(r"[A-Za-z]", label)) < 2:
            return None
        if label.casefold().rstrip(":") in _GENERIC_LABELS:
            return None
        return label

    @staticmethod
    def _meaningful_header(value: str) -> bool:
        clean = value.strip()
        if re.search(r"(?i)^%\s*(?:of\s*)?(?:rmb|usd|cny|hkd|eur|\$|£|€)\b", clean):
            return False
        return (
            bool(clean)
            and clean != "label"
            and clean.casefold().rstrip(":") not in _GENERIC_LABELS
            and not clean.startswith("column_")
            and not _PERIOD.match(clean)
            and clean not in {"$", "£", "€", "%"}
        )

    def _text_observations(self, page: int, text: str) -> list[Observation]:
        pattern = re.compile(r"(?im)^\s*([A-Za-z][A-Za-z /&-]{1,80}?)\s+(?:FY\s*)?((?:19|20)\d{2})\s*(?:=|:|was)\s*([^\n;]+)")
        output: list[Observation] = []
        for match in pattern.finditer(text):
            metric, period, raw = (part.strip() for part in match.groups())
            if number := parse_number(raw):
                confidence = min(0.8, number.confidence)
                semantic = classify_metric(metric, value=number.value, raw_unit=number.raw_unit, unit=number.unit)
                period_sem = classify_period(period)
                unit_val = "multiple" if semantic.is_multiple else ("percent" if semantic.is_percentage else (number.unit or semantic.metric_type))
                output.append(
                    Observation(
                        id=stable_id("observation", page, match.start(), metric, period),
                        metric_original=metric,
                        value=number.value,
                        raw_value=raw,
                        unit=unit_val,
                        raw_unit=number.raw_unit,
                        unit_scale=number.scale,
                        currency=number.currency,
                        period=period,
                        evidence=[SourceEvidence(page=page, text=match.group(0), extraction_method="digital_text", confidence=confidence)],
                        confidence=confidence,
                        semantic_type=semantic.semantic_type,
                        unit_family=semantic.unit_family,
                        display_unit=semantic.display_unit,
                        period_type=period_sem.period_type,
                        audited_status="unaudited" if period_sem.is_unaudited else "audited",
                    )
                )
        return output
