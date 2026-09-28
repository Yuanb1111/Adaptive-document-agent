"""Visible numeric support for conclusions, resolved through analysis input IDs."""

from collections import defaultdict

from adaptive_document_agent.document_model import display_metric_name
from adaptive_document_agent.document_model.series import metric_identity_key
from adaptive_document_agent.document_model.period_semantic_validator import format_observation_period
from adaptive_document_agent.document_model.metric_semantic_classifier import classify_metric
from adaptive_document_agent.validation.presentation_provenance import insight_inputs
from .presentation_evidence import evidence_groups
from .single_metric_analysis import single_metric_analysis


def closing_evidence(result, plan):
    """Return compatible endpoint tables and all original records for notes.

    No metric search or page-based inference can add inputs to a conclusion.
    Incompatible or conflicting series remain individual reported values.
    """
    from .pptx_export import _appendix_display_unit, _appendix_display_value
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
            pairs = [[analysis.observations[0], analysis.observations[-1]]] if analysis else [[o] for o in group]
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
                values = [_appendix_display_value(o, semantic) for o in pair]
                pages = sorted({e.page for o in pair for e in o.evidence})
                tables[(periods, unit)].append((label, values, pages))
    return list(tables.items()), records


def render_evidence_table(slide, table_spec, *, x, y, width):
    from pptx.util import Inches
    from pptx.enum.text import MSO_ANCHOR
    from .pptx_export import _cell_style, FOURIER_PURPLE, FOURIER_DARK, FOURIER_BG_CARD, WHITE
    from .text_capacity import wrap_copy

    (periods, unit), rows = table_spec
    cells = [[f"Reported values ({unit})" if unit else "Reported values", *periods],
             *[[label, *values] for label, values, _ in rows]]
    widths = [width * .46] + [width * .54 / len(periods)] * len(periods)
    heights = [max(.43, max(len(wrap_copy(text, w - .16, 12)) for text, w in zip(row, widths)) * .20 + .12)
               for row in cells]
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
