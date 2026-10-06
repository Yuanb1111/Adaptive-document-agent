"""Visible numeric support for conclusions, resolved through analysis input IDs."""

from collections import defaultdict
from decimal import Decimal
from math import isfinite, ulp
import re

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.document_model.series import metric_identity_key
from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
from adaptive_document_agent.validation.presentation_provenance import insight_inputs
from .presentation_evidence import evidence_groups
from .single_metric_analysis import single_metric_analysis


def closing_evidence(result, plan):
    """Return complete selected series and all original records for notes.

    No metric search or page-based inference can add inputs to a conclusion.
    Incompatible or conflicting series remain individual reported values.
    """
    from .pptx_export import _appendix_display_unit
    links = insight_inputs(result)
    ids = set(plan.observation_ids)
    ids.update(oid for iid in plan.insight_ids for oid in links.get(iid, []))
    records = [o for o in result.observations if o.id in ids]
    scopes = defaultdict(list)
    for o in records:
        if o.value is not None and o.evidence and o.validation_status in {"valid", "partially_valid"}:
            scopes[metric_identity_key(o)].append(o)
    tables = defaultdict(list)
    for scope in scopes.values():
        for group in evidence_groups(scope):
            analysis = single_metric_analysis(group)
            # Endpoint-only tables can hide an explicitly described peak or
            # reversal. Keep every selected point, continuing complete period
            # columns rather than asking Python to reinterpret the prose.
            series = analysis.observations if analysis else None
            pairs = ([series[start:start + 5] for start in range(0, len(series), 5)]
                     if series else [[o] for o in group])
            for pair in pairs:
                periods = tuple(format_observation_period(o) or "Period unspecified" for o in pair)
                source_labels = {e.row_label.strip() for o in pair for e in o.evidence if e.row_label and e.row_label.strip()}
                # A literal source row is more precise than a cached parent label.
                label = next(iter(source_labels)) if len(source_labels) == 1 else display_metric_name(pair[0])
                if pair[0].category_dimensions:
                    qualifiers = [value for value in pair[0].category_dimensions.values()
                                  if value.strip().casefold() != label.casefold()]
                    if qualifiers:
                        label += " — " + ", ".join(qualifiers)
                semantic = classify_metric(display_metric_name(pair[0]), value=pair[0].value,
                                           raw_unit=pair[0].raw_unit, unit=pair[0].unit)
                unit = _appendix_display_unit(pair[0], semantic)
                values = [_exact_closing_value(o, semantic) for o in pair]
                pages = sorted({e.page for o in pair for e in o.evidence})
                tables[(periods, unit)].append((label, values, pages))
    return list(tables.items()), records


def _exact_closing_value(item, semantic) -> str:
    """Keep numeric precision in the existing displayed monetary unit.

    Closing evidence must support the accompanying claims. The appendix's
    compact rounding is unsuitable here: distinct reported points may collapse
    to the same visible integer. Decimal scaling adds no inferred precision.
    """
    from .financial_formatter import normalize_raw_unit, split_unit_basis
    from .pptx_export import _appendix_display_value

    if not semantic.is_currency or item.value is None or split_unit_basis(item.raw_unit)[1]:
        return _appendix_display_value(item, semantic)
    value = Decimal(str(item.value))
    source_unit = normalize_raw_unit(item.raw_unit, default_currency=item.currency).casefold()
    source_scale = (1_000 if "'000" in source_unit or "thousand" in source_unit
                    else 1_000_000_000 if "billion" in source_unit
                    else 1_000_000 if "million" in source_unit else 1)
    if (item.unit_scale or 1.0) <= 1.0:
        # Follow the same explicit source-scale convention as the unit/value
        # formatter; normalized observations already contain base amounts.
        value *= source_scale
    raw = _consistent_source_decimal(item, value, source_scale)
    if raw is not None:
        value = raw
    text = format(value / Decimal(1_000_000), ",f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _consistent_source_decimal(item, base_value: Decimal, source_scale: int) -> Decimal | None:
    """Recover source digits only when they agree with the normalized amount.

    The established parser validates the full raw token and its sign/scale.
    Reading its original decimal digits avoids displaying multiplication noise
    such as 0.29 thousand becoming 289.99999999999994 base units. A materially
    different source value cannot overwrite the normalized observation.
    """
    from adaptive_document_agent.extraction.numeric_parser import parse_number

    parsed = parse_number(item.raw_value)
    if parsed is None:
        return None
    text = item.raw_value.replace("\u00a0", " ").replace(",", "")
    text = re.sub(r"(?<=\d)\s+(?=\d{3}(?:\D|$))", "", text)
    tokens = re.findall(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    if len(tokens) != 1:
        return None
    number = Decimal(tokens[0])
    if parsed.value < 0 and number > 0:
        number = -number
    scale = (parsed.scale if parsed.scale > 1 else item.unit_scale
             if (item.unit_scale or 1) > 1 else source_scale)
    candidate = number * Decimal(str(scale))
    expected, actual = float(base_value), float(candidate)
    if not isfinite(expected) or not isfinite(actual):
        return None
    # Allow only floating-point representation noise, not a decimal rounding
    # tolerance that could erase genuinely different retained source values.
    if abs(expected - actual) <= 4 * max(ulp(expected), ulp(actual)):
        return candidate
    return None


def evidence_table_layout(table_spec, width):
    """Measure the same complete cells used by the editable closing table."""
    from .text_capacity import wrap_copy
    (periods, unit), rows = table_spec
    cells = [[f"Reported values ({unit})" if unit else "Reported values", *periods],
             *[[label, *values] for label, values, _ in rows]]
    widths = [width * .46] + [width * .54 / len(periods)] * len(periods)
    heights = [max(.43, max(len(wrap_copy(text, w - .16, 12)) for text, w in zip(row, widths)) * .20 + .12)
               for row in cells]
    return cells, widths, heights


def render_evidence_table(slide, table_spec, *, x, y, width):
    from pptx.util import Inches
    from pptx.enum.text import MSO_ANCHOR
    from .pptx_export import _cell_style, FOURIER_PURPLE, FOURIER_DARK, FOURIER_BG_CARD, WHITE

    cells, widths, heights = evidence_table_layout(table_spec, width)
    shape = slide.shapes.add_table(len(cells), len(cells[0]), Inches(x), Inches(y), Inches(width), Inches(sum(heights)))
    shape.name = "closing:evidence"
    for j, w in enumerate(widths):
        shape.table.columns[j].width = Inches(w)
    for i, row in enumerate(cells):
        shape.table.rows[i].height = Inches(heights[i])
        for j, text in enumerate(row):
            cell = shape.table.cell(i, j)
            cell.text = text
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            _cell_style(cell, fill=FOURIER_PURPLE if i == 0 else WHITE if i % 2 else FOURIER_BG_CARD,
                        color=WHITE if i == 0 else FOURIER_DARK, bold=i == 0, size=12)
    return shape
