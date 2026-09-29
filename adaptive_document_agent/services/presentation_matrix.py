"""Exact category-by-measure matrix from model-selected source observations."""

from __future__ import annotations

from dataclasses import dataclass
import json

from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period


@dataclass(frozen=True)
class ComparisonMatrix:
    row_labels: tuple[str, ...]
    column_labels: tuple[str, ...]
    cells: tuple[tuple[object, ...], ...]
    observations: tuple


def comparison_matrix(block, index) -> ComparisonMatrix:
    """Accept a fully populated matrix with one source observation per cell."""
    dimension = block.matrix_dimension.strip()
    if not dimension or len(block.observation_ids) < 4 or len(set(block.observation_ids)) != len(block.observation_ids):
        raise ValueError("Matrix needs a named category dimension and distinct source records.")
    items = [index.get(oid) for oid in block.observation_ids]
    if any(item is None or item.value is None or not item.period or not item.evidence
           or item.validation_status != "valid" or item.anomaly_notes for item in items):
        raise ValueError("Matrix cells require valid reported values, periods and citations.")
    rows, columns, cells, scope = [], [], {}, None
    for item in items:
        dims = {**item.dimensions, **item.category_dimensions}
        row = str(dims.pop(dimension, "")).strip()
        if not row:
            raise ValueError("Every matrix record must identify the selected category.")
        other_dims = tuple(sorted((key, str(value)) for key, value in dims.items()
                                  if key not in {"table_context", "section", "column_role", "period_basis"}))
        item_scope = (item.entity, other_dims)
        if scope is None:
            scope = item_scope
        elif item_scope != scope:
            raise ValueError("Matrix cells mix distinct entities or nonselected dimensions.")
        column = (item.metric_original, format_observation_period(item), item.unit,
                  item.raw_unit, item.currency, item.parent_section)
        if row not in rows:
            rows.append(row)
        if column not in columns:
            columns.append(column)
        if (row, column) in cells:
            raise ValueError("Matrix has conflicting or duplicate values for one category and measure.")
        cells[row, column] = item
    if not 2 <= len(rows) <= 6 or not 2 <= len(columns) <= 5:
        raise ValueError("A readable matrix needs two to six categories and two to five measures.")
    if len(cells) != len(rows) * len(columns):
        raise ValueError("Matrix has missing category/measure cells; missing is not zero.")
    names = []
    for metric, period, unit, raw_unit, currency, parent in columns:
        name = f"{parent}: {metric}" if parent and parent.casefold() not in metric.casefold() else metric
        parts = []
        if currency and currency.casefold() not in (raw_unit or "").casefold():
            parts.append(currency)
        parts.append(raw_unit or ("%" if unit == "percent" else unit))
        suffix = " ".join(part for part in parts if part)
        names.append(f"{name}\n{period}" + (f" ({suffix})" if suffix else ""))
    return ComparisonMatrix(tuple(rows), tuple(names),
                            tuple(tuple(cells[row, col] for col in columns) for row in rows), tuple(items))


def render_matrix(presentation, slide_plan, block, index):
    from pptx.util import Inches, Pt
    from .pptx_export import _source_footer, _text, FOURIER_DARK, FOURIER_MUTED, FOURIER_PURPLE
    from .slide_compositor import _base, _lines
    from .presentation_style import FONT

    matrix = comparison_matrix(block, index)
    slide, top = _base(presentation, slide_plan.title, slide_plan.message)
    slide.name = "evidence_comparison_matrix"
    width = presentation.slide_width.inches - 1.1
    first_width = width * .22
    data_width = (width - first_width) / len(matrix.column_labels)
    headers = [block.matrix_dimension, *matrix.column_labels]
    if any(len(_lines(label, data_width - .18, 12)) > 3 for label in matrix.column_labels):
        raise ValueError("Matrix column heading exceeds readable capacity.")
    header_h = .85
    row_h = .78
    total_h = header_h + row_h * len(matrix.row_labels)
    if top + total_h > presentation.slide_height.inches - 1.02:
        raise ValueError("Matrix exceeds readable slide capacity.")
    shape = slide.shapes.add_table(len(matrix.row_labels) + 1, len(headers),
                                   Inches(.55), Inches(top + .08), Inches(width), Inches(total_h))
    shape.name = "table:comparison_matrix:" + ",".join(item.id for item in matrix.observations)
    table = shape.table
    table.columns[0].width = Inches(first_width)
    for j in range(1, len(table.columns)):
        table.columns[j].width = Inches(data_width)
    table.rows[0].height = Inches(header_h)
    for i in range(1, len(table.rows)):
        table.rows[i].height = Inches(row_h)
    for j, label in enumerate(headers):
        table.cell(0, j).text = label
    for i, (row_label, records) in enumerate(zip(matrix.row_labels, matrix.cells), 1):
        table.cell(i, 0).text = row_label
        for j, item in enumerate(records, 1):
            value = item.raw_value.strip() or str(item.value)
            if item.unit == "percent" and item.raw_unit == "%" and "%" not in value:
                value += "%"
            table.cell(i, j).text = value
    for i, row in enumerate(table.rows):
        for cell in row.cells:
            cell.text_frame.word_wrap = True
            for paragraph in cell.text_frame.paragraphs:
                paragraph.font.name = FONT
                paragraph.font.size = Pt(12 if i == 0 else 14)
                paragraph.font.bold = i == 0
                from .pptx_export import _rgb
                paragraph.font.color.rgb = _rgb(FOURIER_PURPLE if i == 0 else FOURIER_DARK)
    pages = sorted({source.page for item in matrix.observations for source in item.evidence})
    _text(slide, _source_footer(pages), .55, presentation.slide_height.inches - .82,
          width, .20, size=9, color=FOURIER_MUTED)
    slide.notes_slide.notes_text_frame.text = json.dumps({
        "matrix_dimension": block.matrix_dimension,
        "source_observations": [item.model_dump(mode="json") for item in matrix.observations],
    }, ensure_ascii=False)
    return slide
