"""Deterministic table/text observations before semantic enrichment."""

import re

from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric, is_multiple_metric
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

            # Deduction detection ("Less:", "减：")
            is_deduction = getattr(row, "is_deduction", False) or bool(re.search(r"(?i)^[:\-\s]*(?:less|减)[:：\s]+", label))
            clean_label = re.sub(r"(?i)^[:\-\s]*(?:less|减)[:：\s]+", "", label).strip() if is_deduction else label

            # Category / hierarchy detection
            is_category_under_metric = False
            if current_section:
                sec_sem = classify_metric(current_section)
                if sec_sem.is_currency or sec_sem.is_percentage:
                    is_category_under_metric = True

            for column in numeric_columns:
                header = table.headers[column] if column < len(table.headers) else f"column_{column + 1}"
                row_period = row.column_periods[column] if column < len(row.column_periods) else None
                table_period = table.column_periods[column] if column < len(table.column_periods) else None
                period = row_period or table_period
                if (any(table.column_periods) or any(row.column_periods)) and not period and not self._meaningful_header(header):
                    continue

                col_type = table.column_types[column] if column < len(table.column_types) else "unknown"
                dimensions: dict[str, str] = {}
                cat_dims: dict[str, str] = {}

                if column_metric_mode and self._meaningful_header(header):
                    metric = f"{current_section}: {header}" if current_section else header
                    dim_key = table.headers[0].casefold() if self._meaningful_header(table.headers[0]) else "category"
                    dimensions[dim_key] = clean_label
                    cat_dims[dim_key] = clean_label
                elif is_category_under_metric:
                    # e.g. Section = "Gross profit", Row = "Mainland"
                    metric = current_section or clean_label
                    dim_key = table.headers[0].casefold() if self._meaningful_header(table.headers[0]) else "category"
                    dimensions[dim_key] = clean_label
                    cat_dims[dim_key] = clean_label
                    if col_type == "percentage":
                        metric = f"{metric} share" if "share" in header.casefold() else f"{metric} margin"
                else:
                    metric = f"{clean_label}: {header}" if self._meaningful_header(header) else clean_label
                    if current_section:
                        dimensions["section"] = current_section

                if is_deduction:
                    dimensions["row_operator"] = "subtractive"
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
                    category_dimensions=cat_dims,
                    column_label=header,
                    column=column,
                    is_deduction=is_deduction,
                    current_section=current_section,
                )
                if item:
                    output.append(item)
        return output

    def _make(
        self,
        table: ExtractedTable,
        row_index: int,
        metric: str,
        raw: str | None,
        *,
        period: str | None = None,
        dimensions: dict[str, str] | None = None,
        category_dimensions: dict[str, str] | None = None,
        column_label: str | None = None,
        column: int | None = None,
        is_deduction: bool = False,
        current_section: str | None = None,
    ) -> Observation | None:
        if raw is None or not (number := parse_number(raw)):
            return None
        unit, currency = number.unit, number.currency
        scale = number.scale
        value = number.value
        col_type = table.column_types[column] if (column is not None and column < len(table.column_types)) else "unknown"

        header_lower = (column_label or "").casefold()
        is_nonsensical_pct_header = bool(re.search(r"(?i)%\s*(?:of\s*)?(?:rmb|usd|cny|hkd|eur|\$|£|€)", header_lower))
        validation_status = "valid"
        anomaly_notes: list[str] = []

        # Multiples are intrinsic and never monetary currency or percentage
        if is_multiple_metric(metric) or col_type == "ratio" or unit == "multiple":
            unit, currency, scale = "multiple", None, 1.0
            value = number.value
            semantic_type = "multiple"
            unit_family = "multiple"
            display_unit = "x"
        elif col_type == "percentage":
            unit, currency, scale = "percent", None, 1.0
            value = number.value
            semantic_type = "margin" if "margin" in metric.casefold() or "利润率" in metric else "ratio_share"
            unit_family = "percentage"
            display_unit = "%"
            if value is not None and (value > 1000.0 or value < -1000.0):
                validation_status = "suspicious_alignment"
                anomaly_notes.append(f"Implausible percentage value {value}% in column '{column_label}'")
        elif col_type == "amount":
            unit = "currency"
            currency = (table.column_currencies[column] if column is not None and column < len(table.column_currencies) and table.column_currencies[column] else None) or table.default_currency
            scale = (table.column_scales[column] if column is not None and column < len(table.column_scales) and table.column_scales[column] else None) or table.default_unit_scale or 1.0
            value = number.value * scale if (number.value is not None and scale != 1.0) else number.value
            semantic_type = "monetary_amount"
            unit_family = "currency"
            display_unit = number.raw_unit or table.default_raw_unit or currency or "currency"
            if "%" in raw:
                validation_status = "suspicious_alignment"
                anomaly_notes.append(f"Amount column contains explicit '%' in raw cell: '{raw}'")
        elif col_type == "days":
            unit, currency, scale = "days", None, 1.0
            value = number.value
            semantic_type = "days"
            unit_family = "days"
            display_unit = "days"
        elif col_type == "count":
            unit, currency, scale = "count", None, 1.0
            value = number.value
            semantic_type = "count"
            unit_family = "count"
            display_unit = "units"
        else:
            # col_type is unknown / generic: determine semantics by metric and header
            semantic = classify_metric(
                metric,
                value=number.value,
                raw_unit=number.raw_unit or table.default_raw_unit,
                unit=unit or table.default_unit,
            )
            if semantic.is_percentage or (("%" in header_lower or "percent" in header_lower) and not is_nonsensical_pct_header):
                unit, currency, scale = "percent", None, 1.0
                value = number.value
                semantic_type = semantic.semantic_type if semantic.is_percentage else ("margin" if "margin" in metric.casefold() or "利润率" in metric else "ratio_share")
                unit_family = "percentage"
                display_unit = "%"
                if value is not None and (value > 1000.0 or value < -1000.0):
                    validation_status = "suspicious_alignment"
                    anomaly_notes.append(f"Implausible percentage value {value}% in column '{column_label}'")
            elif any(term in header_lower for term in ("volume", "quantity", "units sold", "count")):
                unit, currency, scale = "count", None, 1.0
                value = number.value
                semantic_type, unit_family, display_unit = "count", "count", "units"
            elif semantic.is_currency or unit == "currency" or table.default_unit == "currency":
                unit = "currency"
                currency = currency or table.default_currency
                scale = (table.column_scales[column] if column is not None and column < len(table.column_scales) and table.column_scales[column] else None) or table.default_unit_scale or 1.0
                value = number.value * scale if (number.value is not None and scale != 1.0) else number.value
                semantic_type = "monetary_amount"
                unit_family = "currency"
                display_unit = number.raw_unit or table.default_raw_unit or currency or "currency"
                if "%" in raw:
                    validation_status = "suspicious_alignment"
                    anomaly_notes.append(f"Amount column contains explicit '%' in raw cell: '{raw}'")
            else:
                unit = unit or table.default_unit or "generic"
                currency = currency or table.default_currency
                value = number.value
                semantic_type = semantic.semantic_type
                unit_family = semantic.unit_family
                display_unit = semantic.display_unit

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

        is_bs = unit_family == "currency" and any(
            term in metric.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor", "asset", "equity", "资产", "负债", "结余", "现金")
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
            source_table=table.context_label or table.table_id,
            table_id=table.table_id,
            row_id=row_index,
            column_id=column,
            category_dimensions=category_dimensions or {},
            parent_section=current_section or (dimensions.get("section") if dimensions else None),
            row_operator="subtractive" if is_deduction else "additive",
            semantic_confidence=1.0 if validation_status == "valid" else 0.4,
            chartability_status="unassessed",
            anomaly_notes=anomaly_notes,
            semantic_type=semantic_type,
            unit_family=unit_family,
            display_unit=display_unit,
            period_type=period_sem.period_type,
            as_of_date=period_sem.as_of_date or (period_sem.clean_label if (is_bs or period_sem.period_type == "balance_sheet_date") else None),
            audited_status="unaudited" if period_sem.is_unaudited else "audited",
            validation_status=validation_status,
        )

    @staticmethod
    def _row_label(value: str | None) -> str | None:
        if not value:
            return None
        label = " ".join(value.split()).strip()
        if parse_number(label) or label in {"$", "£", "€", "%", "—", "–", "-"}:
            return None
        # Support Unicode letters including Latin and CJK characters
        letters = re.findall(r"[A-Za-z\u3400-\u9fff\u00c0-\u024f]", label)
        if len(letters) < 2:
            return None
        if label.casefold().rstrip(":") in _GENERIC_LABELS:
            return None
        return label

    @staticmethod
    def _meaningful_header(value: str) -> bool:
        clean = value.strip()
        if re.search(r"(?i)^%\s*(?:of\s*)?(?:rmb|usd|cny|hkd|eur|\$|£|€)\b", clean):
            return False
        # If header contains a year (e.g. 2023 Amount) or is a role keyword (Amount, %), it is not a metric
        if re.search(r"(?:19|20)\d{2}", clean) or clean.casefold() in {"amount", "金额", "占比", "份额", "%", "$", "£", "€"}:
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
        pattern = re.compile(r"(?im)^\s*([A-Za-z\u3400-\u9fff][A-Za-z\u3400-\u9fff /&-]{1,80}?)\s+(?:FY\s*)?((?:19|20)\d{2})\s*(?:=|:|was|为|是|：)\s*([^\n;]+)")
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
