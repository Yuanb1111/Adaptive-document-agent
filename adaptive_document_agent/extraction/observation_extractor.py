"""Deterministic table/text observations before semantic enrichment."""

import re

from adaptive_document_agent.document_model.metric_semantic_classifier import (
    classify_metric,
    format_metric_display_value,
    is_days_metric,
    is_explicit_count_metric,
    is_financial_statement_metric,
    is_margin_metric,
    is_multiple_metric,
    sanitize_metric_label,
)
from adaptive_document_agent.document_model.period_semantic_validator import (
    classify_period,
    extract_period_basis,
)
from adaptive_document_agent.models import Observation, ParsedDocument, SourceEvidence
from adaptive_document_agent.models.table import ExtractedTable
from adaptive_document_agent.utils.ids import stable_id

from .numeric_parser import parse_number
from .column_roles import explicit_percentage, intrinsic_percentage
from .normalizer import infer_unit_defaults
from .unit_evidence import cell_unit_defaults
from .comparison_context import table_comparison_contexts, with_comparison_context

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
        # Rebuild stale/inferred percentage roles from the source grid before
        # synthetic '%' headers can contaminate metric names and semantic typing.
        if table.raw_cells and "percentage" in table.column_types:
            from .table_reconstructor import TableReconstructor
            table = TableReconstructor().reconstruct(table)
        if len(table.headers) < 2 or not table.rows:
            return []
        output: list[Observation] = []
        meaningful_header_list = [
            header
            for header in table.headers[1:]
            if self._meaningful_header(header)
        ]
        column_metric_mode = len(set(meaningful_header_list)) >= 2
        comparison_contexts = table_comparison_contexts(table)
        current_section: str | None = None
        for row_index, row in enumerate(table.rows):
            if row.alignment_status == "ambiguous":
                # Preserve unresolved cells in the source table. Never shift
                # them into year/percentage slots merely to emit observations.
                current_section = None
                continue
            if not row.cells:
                continue
            numeric_columns = [column for column, raw in enumerate(row.cells[1:], start=1) if raw and parse_number(raw)]
            # Generic words can be explicit scope headings (e.g. "Current" or
            # "Other"). They are insufficient standalone metrics, but must not
            # disappear from the identity of the following source rows.
            label = self._row_label(row.cells[0], allow_generic=not numeric_columns)
            if label and not numeric_columns:
                # Operators are not semantic parent metrics. Keep their raw
                # source row without prefixing all subsequent results with Add.
                current_section = None if re.fullmatch(r"(?i)(?:add|less|adjustments?|加|减|调整)[:：]?", label.strip()) else label.rstrip(":")
                continue
            if not label:
                # Bare totals are intentionally not emitted as observations;
                # they still close the preceding source group.
                if (row.cells[0] or "").strip().casefold() in {"total", "grand total", "合计", "总计"}:
                    current_section = None
                continue

            # Deduction detection ("Less:", "减：")
            is_deduction = getattr(row, "is_deduction", False) or bool(re.search(r"(?i)^[:\-\s]*(?:less|减)[:：\s]+", label))
            clean_label = re.sub(r"(?i)^[:\-\s]*(?:less|减)[:：\s]+", "", label).strip() if is_deduction else label

            # Category / hierarchy detection
            is_category_under_metric = False
            if current_section:
                sec_sem = classify_metric(current_section)
                if (sec_sem.is_currency or sec_sem.is_percentage) and not re.search(r"(?i)\b(?:related to|for|from|by)\s*$", current_section):
                    is_category_under_metric = True

            for column in numeric_columns:
                header = table.headers[column] if column < len(table.headers) else f"column_{column + 1}"
                row_period = row.column_periods[column] if column < len(row.column_periods) else None
                table_period = table.column_periods[column] if column < len(table.column_periods) else None
                period = row_period or table_period
                if (any(table.column_periods) or any(row.column_periods)) and not period and not self._meaningful_header(header):
                    continue

                is_pct_col = explicit_percentage(header) or explicit_percentage(row.cells[column])
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
                    if is_pct_col:
                        metric = f"{metric} share" if "share" in header.casefold() else f"{metric} margin"
                        dimensions["column_role"] = "percentage"
                    else:
                        dimensions["column_role"] = "amount"
                else:
                    if is_pct_col:
                        if self._meaningful_header(header):
                            metric = f"{clean_label}: {header}"
                        elif "gross profit" in clean_label.casefold() or "毛利" in clean_label:
                            metric = f"{clean_label} margin"
                        elif "net profit" in clean_label.casefold() or "net income" in clean_label.casefold() or "net loss" in clean_label.casefold():
                            metric = f"{clean_label} %"
                        elif "margin" in header.casefold() or "利润率" in header:
                            metric = f"{clean_label} margin"
                        elif "share" in header.casefold() or "份额" in header or "占比" in header:
                            metric = f"{clean_label} share"
                        else:
                            metric = f"{clean_label} %"
                        dimensions["column_role"] = "percentage"
                    else:
                        metric = f"{clean_label}: {header}" if self._meaningful_header(header) else clean_label
                        dimensions["column_role"] = "amount"
                    if current_section:
                        dimensions["section"] = current_section

                if is_deduction:
                    dimensions["row_operator"] = "subtractive"
                basis = extract_period_basis(period)
                if re.fullmatch(r'(?:1[0-2]|[1-9])M', basis) or (period and period.startswith('FY')):
                    dimensions["period_basis"] = basis
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
                    output.append(with_comparison_context(item, comparison_contexts))
            # An explicitly named group total closes that group. Subsequent
            # rows are independent until another source heading opens a group.
            # A subtotal does not close the parent: more components may follow.
            if current_section:
                total_for = re.sub(r"(?i)^(?:grand\s+)?total\s+", "", clean_label).strip().casefold()
                if clean_label.casefold() in {"total", "grand total", "合计", "总计"} or (
                    total_for != clean_label.casefold() and total_for == current_section.casefold()
                ):
                    current_section = None
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
        source_units = cell_unit_defaults(table, row_index, column_label)
        row_units = infer_unit_defaults(table.rows[row_index].cells[0] or "")
        column_units = infer_unit_defaults(column_label or "")
        local_currency = number.currency or row_units.currency or column_units.currency
        column_currency = (
            table.column_currencies[column]
            if source_units.allow_column_defaults and column is not None and column < len(table.column_currencies)
            else None
        )

        header_lower = (column_label or "").casefold()
        is_nonsensical_pct_header = bool(re.search(r"(?i)%\s*(?:of\s*)?(?:rmb|usd|cny|hkd|eur|\$|£|€)", header_lower))
        validation_status = "valid"
        anomaly_notes: list[str] = []

        # Bare "share of" wording is not percentage evidence: a monetary
        # allocation may use that wording too. Use intrinsic ratio semantics
        # or explicit source units instead; never discard its currency/scale.
        is_explicit_pct = intrinsic_percentage(metric) or explicit_percentage(raw) or explicit_percentage(column_label) or any(
            k in metric.casefold() for k in ("margin", "% of", "as %", "growth rate", "cagr", "proportion", "毛利率", "净利率", "利润率", "占比", "比例", "增长率")
        )
        is_monetary_item = is_financial_statement_metric(metric) and not is_explicit_pct
        column_scale = (
            table.column_scales[column]
            if source_units.allow_column_defaults and column is not None and column < len(table.column_scales) and col_type != "percentage"
            else None
        )
        # "amount" is also the table parser's fallback for an untyped numeric
        # column. It is not evidence of currency. Explicit counts/volume outrank
        # a table's monetary default, while a conflicting cell/row unit is kept.
        count_metric = is_explicit_count_metric(metric) or classify_metric(metric).unit_family == "count"
        is_count = count_metric or (col_type == "count" and not is_monetary_item)
        monetary_evidence = is_monetary_item or bool(local_currency or column_currency or source_units.currency) or unit == "currency" or source_units.unit == "currency"

        if is_multiple_metric(metric) or col_type == "ratio" or unit == "multiple":
            unit, currency, scale = "multiple", None, 1.0
            value = number.value
            semantic_type = "multiple"
            unit_family = "multiple"
            display_unit = "x"
        elif is_explicit_pct:
            unit, currency, scale = "percent", None, 1.0
            value = number.value
            semantic_type = "margin" if (is_margin_metric(metric) or "margin" in metric.casefold() or "利润率" in metric) else "ratio_share"
            unit_family = "percentage"
            display_unit = "%"
            if value is not None and (value > 1000.0 or value < -1000.0):
                validation_status = "suspicious_alignment"
                anomaly_notes.append(f"Implausible percentage value {value}% in column '{column_label}'")
        elif is_days_metric(metric) or col_type == "days":
            unit, currency, scale = "days", None, 1.0
            value = number.value
            semantic_type = "days"
            unit_family = "days"
            display_unit = "days"
        elif is_count and not local_currency:
            unit, currency, scale = "count", None, number.scale
            value = number.value
            semantic_type, unit_family, display_unit = "count", "count", "units"
            dimensions = {**(dimensions or {}), "column_role": "count"}
        elif monetary_evidence:
            unit = "currency"
            currency = local_currency or column_currency or source_units.currency
            if number.scale != 1.0:
                scale = number.scale
            elif row_units.currency:
                scale = row_units.scale or 1.0
            else:
                scale = column_units.scale or source_units.scale or column_scale or 1.0
            value = number.value * scale if scale != 1.0 and number.scale == 1.0 else number.value
            semantic_type = "monetary_amount"
            unit_family = "currency"
            display_unit = number.raw_unit or source_units.raw_unit or currency or "currency"
            if is_count:
                validation_status = "suspicious_alignment"
                anomaly_notes.append("Explicit count label conflicts with a source currency unit; source value and unit retained.")
            if "%" in raw and not is_monetary_item:
                validation_status = "suspicious_alignment"
                anomaly_notes.append(f"Amount column contains explicit '%' in raw cell: '{raw}'")
        elif col_type == "count" and not is_financial_statement_metric(metric):
            unit, currency, scale = "count", None, 1.0
            value = number.value
            semantic_type = "count"
            unit_family = "count"
            display_unit = "units"
        else:
            # col_type is unknown / generic / financial: determine semantics by metric and header
            semantic = classify_metric(
                metric,
                value=number.value,
                raw_unit=number.raw_unit or source_units.raw_unit,
                unit=unit or source_units.unit,
            )
            is_fin = is_financial_statement_metric(metric) or semantic.is_currency
            if not is_monetary_item and (semantic.is_percentage or (("%" in header_lower or "percent" in header_lower) and not is_nonsensical_pct_header)):
                unit, currency, scale = "percent", None, 1.0
                value = number.value
                semantic_type = semantic.semantic_type if semantic.is_percentage else ("margin" if "margin" in metric.casefold() or "利润率" in metric else "ratio_share")
                unit_family = "percentage"
                display_unit = "%"
                if value is not None and (value > 1000.0 or value < -1000.0):
                    validation_status = "suspicious_alignment"
            elif (
                not is_fin
                and (
                    any(term in header_lower for term in ("volume", "quantity", "units sold", "count", "shipment", "sales volume", "出货量", "销售量", "销量"))
                    or (
                        any(term in metric.casefold() for term in ("volume", "quantity", "units sold", "shipment", "sales volume", "number of units", "fleet size", "heads", "sets", "pieces", "销量", "销售量", "出货量", "数量", "台", "件", "套"))
                        and not any(asp in metric.casefold() for asp in ("average selling price", "asp", "unit price", "price per", "单价", "平均售价"))
                    )
                )
            ):
                unit, currency, scale = "count", None, 1.0
                value = number.value
                semantic_type, unit_family, display_unit = "count", "count", "units"
            elif is_fin or unit == "currency" or source_units.unit == "currency" or source_units.currency:
                unit = "currency"
                currency = currency or column_currency or source_units.currency
                scale = number.scale if number.scale != 1.0 else column_scale or source_units.scale or 1.0
                value = number.value * scale if scale != 1.0 and number.scale == 1.0 else number.value
                semantic_type = "monetary_amount"
                unit_family = "currency"
                display_unit = number.raw_unit or source_units.raw_unit or currency or "currency"
                if "%" in raw:
                    validation_status = "suspicious_alignment"
                    anomaly_notes.append(f"Amount column contains explicit '%' in raw cell: '{raw}'")
            else:
                unit = unit or source_units.unit or (semantic.metric_type if semantic.unit_family != "generic" else "unknown")
                currency = currency or source_units.currency
                value = number.value
                semantic_type = semantic.semantic_type
                unit_family = semantic.unit_family
                display_unit = semantic.display_unit if semantic.display_unit else (unit or "")

        confidence = min(table.confidence, number.confidence, 0.9 if period else 0.75)
        evidence = SourceEvidence(
            page=table.rows[row_index].page,
            text=raw,
            table_id=table.table_id,
            row_label=table.rows[row_index].cells[0],
            column_label=column_label,
            extraction_method="digital_table",
            confidence=confidence,
        )

        is_bs = unit_family == "currency" and any(
            term in metric.casefold() for term in ("liabilit", "cash", "balance", "receiv", "payab", "inventor", "asset", "equity", "资产", "负债", "结余", "现金")
        )
        # Explicit flow headers outrank a word such as cash or liabilities in
        # the measure name. A six-month movement is not a June closing balance.
        header_text=' '.join(table.raw_header_lines)
        explicit_flow=bool(re.search(r'(?i)\b(?:months?|years?)\s+ended\b',header_text))
        explicit_stock=bool(re.search(r'(?i)\bas\s+(?:at|of)\b',header_text))
        if explicit_flow and not explicit_stock:
            is_bs=False
        period_sem = classify_period(period, is_balance_sheet=is_bs)
        pres_label = sanitize_metric_label(metric)
        disp_val = ""
        if unit_family == "percentage":
            effective_raw_unit = number.raw_unit or "%"
        elif unit_family in {"count", "days", "multiple"}:
            effective_raw_unit = number.raw_unit
        else:
            effective_raw_unit = number.raw_unit or source_units.raw_unit
        if value is not None:
            semantic_obj = classify_metric(
                "" if is_count and local_currency else metric,
                value=value, raw_unit=effective_raw_unit, unit=unit,
            )
            disp_val = format_metric_display_value(
                raw,
                value,
                semantic_obj,
                raw_unit=effective_raw_unit,
                currency=currency,
                compact=False,
            )

        return Observation(
            id=stable_id("observation", table.table_id, row_index, column, column_label, period, raw),
            metric_original=metric,
            value=value,
            raw_value=raw,
            unit=unit,
            raw_unit=effective_raw_unit,
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
            display_value=disp_val,
            presentation_label=pres_label,
            normalized_value=value,
            normalized_unit=unit,
            period_type=period_sem.period_type,
            period_basis=extract_period_basis(period),
            as_of_date=period_sem.as_of_date or (period_sem.clean_label if (is_bs or period_sem.period_type == "balance_sheet_date") else None),
            audited_status=(table.column_audit_statuses[column]
                            if column is not None and column < len(table.column_audit_statuses)
                            else "unaudited" if period_sem.is_unaudited else "unknown"),
            ifrs_status="ADJUSTED" if any(k in f"{metric}".casefold() for k in ("adjusted", "non-ifrs", "non-gaap", "经调整", "非国际财务报告准则")) else "IFRS",
            fact_type="reported_fact",
            validation_status=validation_status,
        )

    @staticmethod
    def _row_label(value: str | None, *, allow_generic: bool = False) -> str | None:
        if not value:
            return None
        label = " ".join(value.split()).strip()
        if parse_number(label) or label in {"$", "£", "€", "%", "—", "–", "-"}:
            return None
        # Support Unicode letters including Latin and CJK characters
        letters = re.findall(r"[A-Za-z\u3400-\u9fff\u00c0-\u024f]", label)
        if len(letters) < 2:
            return None
        if not allow_generic and label.casefold().rstrip(":") in _GENERIC_LABELS:
            return None
        return label

    @staticmethod
    def _meaningful_header(value: str) -> bool:
        clean = value.strip()
        if re.fullmatch(r"(?i)(?:RMB|CNY|USD|HKD|EUR|GBP|HK\$|US\$)(?:\s*(?:in\s*)?(?:['’]000|thousands?|millions?|billions?))?",clean):
            return False
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
                pres_label = sanitize_metric_label(metric)
                disp_val = format_metric_display_value(
                    raw,
                    number.value,
                    semantic,
                    raw_unit=number.raw_unit,
                    currency=number.currency,
                    compact=False,
                )
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
                        display_value=disp_val,
                        presentation_label=pres_label,
                        normalized_value=number.value,
                        normalized_unit=unit_val,
                        period_type=period_sem.period_type,
                        audited_status="unaudited" if period_sem.is_unaudited else "unknown",
                    )
                )
        output.extend(self._extract_vertical_text_series(page, text))
        seen_keys: set[tuple[str, str | None]] = set()
        deduped: list[Observation] = []
        for item in output:
            key = (item.metric_original.casefold(), item.period)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(item)
        return deduped

    def _extract_vertical_text_series(self, page: int, text: str) -> list[Observation]:
        """Deterministic financial text fallback for vertical series:
        Metric (unit)
        2023  xxx
        2024  xxx
        2025  xxx
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        period_row_re = re.compile(
            r"^((?:(?:FY|1H|2H|3M|6M|9M|12M|Q[1-4])\s*)?(?:19|20)\d{2}(?:\s*(?:FY|1H|2H|3M|6M|9M|12M|Q[1-4]))?(?:年|年度)?)\s*(?:[:=：\-—]\s*|\s{1,8})([^\n;]+)$",
            re.IGNORECASE,
        )

        output: list[Observation] = []
        i = 0
        while i < len(lines):
            cand_line = lines[i]
            if period_row_re.match(cand_line) or len(cand_line) > 70 or len(cand_line) < 2:
                i += 1
                continue
            if re.match(r"^(?:page|p\.|\-|\d+)", cand_line.casefold()):
                i += 1
                continue

            unit_hint = ""
            m_unit = re.match(r"^([^\(（]+)(?:[\(（]([^\)）]+)[\)）])?$", cand_line)
            if m_unit:
                base_label = m_unit.group(1).strip()
                unit_hint = m_unit.group(2).strip() if m_unit.group(2) else ""
            else:
                base_label = cand_line.strip()

            if not any(c.isalpha() or "\u4e00" <= c <= "\u9fff" for c in base_label):
                i += 1
                continue

            sem = classify_metric(base_label)
            is_fin = is_financial_statement_metric(base_label) or sem.is_currency or sem.is_percentage
            if not is_fin and sem.metric_type == "unknown":
                i += 1
                continue

            j = i + 1
            pairs: list[tuple[str, str, object]] = []
            while j < len(lines):
                match = period_row_re.match(lines[j])
                if not match:
                    break
                period_str = match.group(1).strip()
                val_str = match.group(2).strip()
                num = parse_number(val_str)
                if num is None or num.value is None:
                    break
                pairs.append((period_str, val_str, num))
                j += 1

            if len(pairs) >= 2:
                default_currency = None
                default_scale = 1.0
                default_unit = None
                if unit_hint:
                    from .normalizer import infer_unit_defaults

                    defaults = infer_unit_defaults(unit_hint)
                    default_currency = defaults.currency
                    default_scale = defaults.scale or 1.0
                    default_unit = defaults.unit
                    if not default_currency and not defaults.scale:
                        hint_num = parse_number(f"1 {unit_hint}")
                        if hint_num:
                            default_currency = hint_num.currency
                            default_scale = hint_num.scale
                            default_unit = hint_num.unit

                for period_str, val_str, num in pairs:
                    period_sem = classify_period(period_str)
                    currency = num.currency or default_currency
                    scale = num.scale if num.scale != 1.0 else default_scale
                    value = (
                        num.value * scale
                        if (num.value is not None and scale != 1.0 and (currency or default_unit == "currency"))
                        else num.value
                    )

                    is_pct = (
                        sem.is_percentage
                        or "%" in val_str
                        or (default_unit == "percent")
                        or (unit_hint and "%" in unit_hint)
                    )
                    if is_pct:
                        unit_val = "percent"
                        currency = None
                        scale = 1.0
                        value = num.value
                        sem_type = (
                            "margin"
                            if "margin" in base_label.casefold() or "利润率" in base_label
                            else "ratio_share"
                        )
                        unit_fam = "percentage"
                        disp_unit = "%"
                    elif is_multiple_metric(base_label) or (default_unit == "multiple"):
                        unit_val = "multiple"
                        currency = None
                        scale = 1.0
                        sem_type = "multiple"
                        unit_fam = "multiple"
                        disp_unit = "x"
                    else:
                        unit_val = num.unit or default_unit or ("currency" if (currency or is_fin) else sem.metric_type)
                        sem_type = "monetary_amount" if (currency or unit_val == "currency") else sem.semantic_type
                        unit_fam = "currency" if (currency or unit_val == "currency") else sem.unit_family
                        disp_unit = unit_hint or num.raw_unit or currency or sem.display_unit

                    pres_label = sanitize_metric_label(base_label)
                    disp_val = format_metric_display_value(
                        val_str,
                        value,
                        sem,
                        raw_unit=num.raw_unit or unit_hint,
                        currency=currency,
                        compact=False,
                    )
                    confidence = 0.85
                    evidence_text = f"{cand_line}\n{period_str} {val_str}"

                    output.append(
                        Observation(
                            id=stable_id("observation", "text_fallback", page, base_label, period_str),
                            metric_original=base_label,
                            value=value,
                            raw_value=val_str,
                            unit=unit_val,
                            raw_unit=num.raw_unit or unit_hint,
                            unit_scale=scale,
                            currency=currency,
                            period=period_str,
                            evidence=[
                                SourceEvidence(
                                    page=page,
                                    text=evidence_text,
                                    extraction_method="digital_text",
                                    confidence=confidence,
                                )
                            ],
                            confidence=confidence,
                            semantic_type=sem_type,
                            unit_family=unit_fam,
                            display_unit=disp_unit,
                            display_value=disp_val,
                            presentation_label=pres_label,
                            normalized_value=value,
                            normalized_unit=unit_val,
                            period_type=period_sem.period_type,
                            audited_status="unaudited" if period_sem.is_unaudited else "unknown",
                        )
                    )
                i = j
            else:
                i += 1

        return output
