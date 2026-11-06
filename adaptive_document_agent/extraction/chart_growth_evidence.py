"""Recover literal units and CAGR cells from a positioned chart above its data grid."""
import re
from math import isfinite

from adaptive_document_agent.models import Observation, SourceEvidence
from adaptive_document_agent.utils.ids import stable_id
from .normalizer import infer_unit_defaults
from .numeric_parser import parse_number

_YEAR = re.compile(r'(?:19|20)\d{2}E?', re.I)
_CAGR = re.compile(r'CAGR\s+((?:19|20)\d{2}E?)\s*[-–—]\s*((?:19|20)\d{2}E?)', re.I)
_RATE = re.compile(r'[+-]?\d+(?:\.\d+)?%')
CHART_MONEY_UNIT = re.compile(
    r'(?<!\w)(?:US\$|HK\$|USD|HKD|RMB|CNY|EUR|GBP)\s+(?:in\s+)?(?:thousands?|millions?|billions?)\b', re.I)


def _lines(page, bounds):
    left, top, right, bottom = bounds
    for block in page.text_blocks:
        for line in block.get('lines') or ():
            if not isinstance(line, dict) or not isinstance(line.get('text'), str):
                continue
            box = line.get('bbox')
            text = line['text'].strip()
            if (text and isinstance(box, (list, tuple)) and len(box) == 4
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v) for v in box)
                    and left - 1 <= box[0] <= box[2] <= right + 1
                    and top - 1 <= box[1] <= box[3] <= bottom + 1):
                yield text, tuple(box)


def _center(box, axis):
    return (box[axis] + box[axis + 2]) / 2


def _chart_header(lines, periods):
    # Require a complete, unique year tier in left-to-right order. A CAGR
    # legend beside another table or a prose mention supplies no units.
    tiers = []
    for text, box in lines:
        if text != periods[0]:
            continue
        tier = sorted(((_center(b, 0), t) for t, b in lines
                       if _YEAR.fullmatch(t) and abs(_center(b, 1) - _center(box, 1)) <= 2))
        if [t for _, t in tier] == periods:
            tiers.append((_center(box, 1), tier[0][0]))
    if len(tiers) != 1:
        return None
    axis_y, axis_left = tiers[0]
    heads = [(m, box) for text, box in lines
             if (m := _CAGR.fullmatch(text)) and box[3] < axis_y
             and m[1] in periods and m[2] in periods and periods.index(m[1]) < periods.index(m[2])]
    if len(heads) < 2 or len({m.groups() for m, _ in heads}) != len(heads):
        return None
    y = _center(heads[0][1], 1)
    if any(abs(_center(box, 1) - y) > 2 for _, box in heads):
        return None
    units = [(text, box) for text, box in lines
             if CHART_MONEY_UNIT.fullmatch(text) and y < box[1] < axis_y and box[2] < axis_left]
    if len(units) != 1:
        return None
    return axis_y, heads, units[0]


def _row_rates(lines, name, axis_y, heads):
    labels = [box for text, box in lines if text == name]
    above = [box for box in labels if heads[0][1][3] < box[1] and box[3] < axis_y]
    if len(above) != 1 or sum(box[1] > axis_y for box in labels) != 1:
        return []
    label = above[0]
    rates = []
    for heading, box in heads:
        candidates = [(text, bounds) for text, bounds in lines if _RATE.fullmatch(text)
                      and abs(_center(bounds, 1) - _center(label, 1)) <= 2
                      and box[0] <= _center(bounds, 0) <= box[2] and label[2] < bounds[0]]
        if len(candidates) != 1:
            return []
        rates.append((heading, *candidates[0]))
    return rates


def chart_growth_observations(document, observations, *, analysis_plan=(), analysis_results=()):
    """Retain raw cells while adding chart-unit provenance and separately reported rates.

    Saved amount-dependent results keep their original input scale. A saved
    ratio is safe to reuse only when all its inputs receive the same multiplier.
    """
    by_table = {}
    for o in observations:
        if o.effective_table_id and o.unit in {None, '', 'unknown'} and not o.currency:
            by_table.setdefault(o.effective_table_id, []).append(o)
    replacements, reported = {}, {}
    existing = {o.id for o in observations}
    tools = {task.id: task.tool_name for task in analysis_plan}
    for page in document.pages:
        for table in page.tables:
            candidates = by_table.get(table.table_id, ())
            periods = table.column_periods[1:]
            if (not candidates or not table.bbox or table.source_rotation or page.reading_rotation
                    or len(periods) < 3 or len(set(periods)) != len(periods)
                    or any(not p or not _YEAR.fullmatch(p) for p in periods)):
                continue
            lines = list(_lines(page, table.bbox))
            header = _chart_header(lines, periods)
            if header is None:
                continue
            axis_y, heads, (unit, unit_box) = header
            defaults = infer_unit_defaults(unit)
            if not defaults.currency or not defaults.scale:
                continue
            rows = {}
            for o in candidates:
                if (o.row_id is None or o.column_id is None or o.value is None
                        or o.validation_status != 'valid' or o.unit_scale not in (None, 1)
                        or not 0 <= o.row_id < len(table.rows) or not 1 <= o.column_id <= len(periods)
                        or o.period != periods[o.column_id - 1]
                        or not any(e.page == page.page_number and e.table_id == table.table_id for e in o.evidence)):
                    continue
                row = table.rows[o.row_id]
                parsed = parse_number(o.raw_value)
                if (row.alignment_status == 'resolved' and row.page == page.page_number
                        and o.column_id < len(row.cells) and row.cells[o.column_id] == o.raw_value
                        and row.cells[0] == o.metric_original and parsed is not None
                        and parsed.value == o.value and isfinite(o.value * defaults.scale)):
                    rows.setdefault(o.metric_original, []).append(o)
            verified = {name: rates for name in rows if (rates := _row_rates(lines, name, axis_y, heads))}
            eligible = {o.id for name in verified for o in rows[name]}
            for result in analysis_results:
                inputs = set(result.input_observation_ids)
                if inputs & eligible and (tools.get(result.task_id) not in {'cagr', 'growth_rate', 'percentage_change'}
                                          or not inputs <= eligible):
                    eligible.difference_update(inputs)
            # Remove partially scaled inputs of overlapping saved ratios too.
            while True:
                unsafe = {oid for result in analysis_results
                          if set(result.input_observation_ids) - eligible
                          for oid in result.input_observation_ids if oid in eligible}
                if not unsafe:
                    break
                eligible.difference_update(unsafe)
            for name, rates in verified.items():
                for o in rows[name]:
                    if o.id not in eligible:
                        continue
                    value = o.value * defaults.scale
                    evidence = SourceEvidence(page=page.page_number, table_id=table.table_id,
                        text=unit, bbox=unit_box, extraction_method='digital_chart_axis', confidence=o.confidence)
                    replacements[o.id] = o.model_copy(update=dict(value=value, normalized_value=value,
                        unit='currency', raw_unit=unit, currency=defaults.currency, unit_scale=defaults.scale,
                        unit_family='currency', semantic_type='monetary_amount', normalized_unit='currency',
                        display_unit=unit, display_value=f'{o.raw_value} {unit}', evidence=[*o.evidence, evidence]))
                for heading, raw, box in rates:
                    identifier = stable_id('reported_chart_cagr', table.table_id, name, heading[1], heading[2])
                    if identifier in existing:
                        continue
                    value = float(raw[:-1])
                    reported[identifier] = Observation(id=identifier, metric_original=f'{name} CAGR',
                        raw_value=raw, value=value, unit='percent', raw_unit='%', unit_scale=1,
                        unit_family='percentage', table_id=table.table_id, period=f'{heading[1]}–{heading[2]}',
                        dimensions={'chart_reported_cagr': name}, confidence=table.confidence,
                        evidence=[SourceEvidence(page=page.page_number, table_id=table.table_id, text=raw,
                            row_label=name, column_label=heading[0], bbox=box,
                            extraction_method='digital_chart_cell', confidence=table.confidence)])
    return [replacements.get(o.id, o) for o in observations] + list(reported.values())
